
import warnings
warnings.filterwarnings('ignore')


import numpy as np
nan = float('nan')
import traceback


from pprint import pprint
from collections import Counter
from multiprocessing import cpu_count
from time import time
from tabulate import tabulate
try: from tqdm import tqdm
except: tqdm = lambda x: x

import sklearn.model_selection
from sklearn.cluster import KMeans
from sklearn.model_selection import StratifiedShuffleSplit as sss, ShuffleSplit as ss, GridSearchCV, TimeSeriesSplit
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, ExtraTreesClassifier, ExtraTreesRegressor, AdaBoostClassifier, AdaBoostRegressor
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sklearn import model_selection


TREE_N_ENSEMBLE_MODELS = [RandomForestClassifier, GradientBoostingClassifier, DecisionTreeClassifier, DecisionTreeRegressor,ExtraTreesClassifier, ExtraTreesRegressor, AdaBoostClassifier, AdaBoostRegressor]


class GridSearchCVProgressBar(sklearn.model_selection.GridSearchCV):
    def _get_param_iterator(self):
        iterator = super(GridSearchCVProgressBar, self)._get_param_iterator()
        iterator = list(iterator)
        n_candidates = len(iterator)
        cv = sklearn.model_selection._split.check_cv(self.cv, None)
        n_splits = getattr(cv, 'n_splits', 3)
        max_value = n_candidates * n_splits
        class ParallelProgressBar(sklearn.model_selection._search.Parallel):
            def __call__(self, iterable):
                iterable = tqdm(iterable, total=max_value)
                iterable.set_description("GridSearchCV")
                return super(ParallelProgressBar, self).__call__(iterable)
        sklearn.model_selection._search.Parallel = ParallelProgressBar
        return iterator


class RandomizedSearchCVProgressBar(sklearn.model_selection.RandomizedSearchCV):
    def _get_param_iterator(self):
        iterator = super(RandomizedSearchCVProgressBar, self)._get_param_iterator()
        iterator = list(iterator)
        n_candidates = len(iterator)
        cv = sklearn.model_selection._split.check_cv(self.cv, None)
        n_splits = getattr(cv, 'n_splits', 3)
        max_value = n_candidates * n_splits
        class ParallelProgressBar(sklearn.model_selection._search.Parallel):
            def __call__(self, iterable):
                iterable = tqdm(iterable, total=max_value)
                iterable.set_description("RandomizedSearchCV")
                return super(ParallelProgressBar, self).__call__(iterable)
        sklearn.model_selection._search.Parallel = ParallelProgressBar
        return iterator


def upsample_indices_clf(inds, y):
    assert len(inds) == len(y)
    countByClass = dict(Counter(y))
    maxCount = max(countByClass.values())
    extras = []
    for klass, count in countByClass.items():
        if maxCount == count: continue
        ratio = int(maxCount / count)
        cur_inds = inds[y == klass]
        extras.append(np.concatenate( (np.repeat(cur_inds, ratio - 1), np.random.choice(cur_inds, maxCount - ratio * count, replace=False))))
    return np.concatenate([inds] + extras)


def cv_clf(x, y, test_size = 0.2, n_splits = 5, random_state=None, doesUpsample = True):
    #splitter  = TimeSeriesSplit(n_splits=n_splits, max_train_size=None).split(x)
    splitter   = sss            (n_splits=n_splits, test_size=  test_size, random_state=random_state).split(x, y)
    if not doesUpsample:
        yield splitter
    for train_index, test_index in splitter:#for train_index, test_index in sss.split(X, y):
        #for train_index, test_index in tscv.split(X):
        yield (upsample_indices_clf(train_index, y[train_index]), test_index)


def cv_reg(x, test_size = 0.2, n_splits = 5, random_state=None): return ss(n_splits, test_size, random_state=random_state).split(x)


def timeit(klass, params, x, y):
    start = time()
    clf = klass(**params)
    clf.fit(x, y)
    return time() - start

def timeit2(clf_search, x, y):
    start = time()
    clf_search.fit(x, y)
    return time() - start


def main_loop(models_n_params, x, y, isClassification, test_size = 0.2, n_splits = 5, random_state=None, upsample=True, scoring=None, verbose=True, n_jobs =cpu_count() - 1, brain=False, grid_search=True):
    def cv_(): return cv_clf(x, y, test_size, n_splits, random_state, upsample) if isClassification else cv_reg(x, test_size, n_splits, random_state)
    res = []
    num_features = x.shape[1]
    scoring = scoring or ('accuracy' if isClassification else 'neg_mean_squared_error')
    if brain: print('Scoring criteria:', scoring)
    for i, (clf_Klass, parameters) in enumerate(tqdm(models_n_params)):
        try:
            if brain:
                print('-'*15, 'model %d/%d' % (i+1, len(models_n_params)), '-'*15)
                print(clf_Klass.__name__)
            if clf_Klass == KMeans:
                parameters['n_clusters'] = [len(np.unique(y))]
            elif clf_Klass in TREE_N_ENSEMBLE_MODELS:
                parameters['max_features'] = [v for v in parameters['max_features'] if v is None or type(v)==str or v<=num_features]
            if grid_search:
                clf_search = GridSearchCVProgressBar(clf_Klass(), parameters, scoring, cv=cv_(), n_jobs=n_jobs)
            else:
                clf_search = RandomizedSearchCVProgressBar(clf_Klass(), parameters, scoring, cv=cv_(), n_jobs=n_jobs)
            time_grid = timeit2(clf_search,x, y)
            time_fit  = timeit(clf_Klass, clf_search.best_params_, x, y)
            if brain:
                print('best score:', clf_search.best_score_, 'time/clf: %0.3f seconds' % time_fit)
                print('best params:')
                pprint(clf_search.best_params_)
            if verbose:
                print('validation scores:', clf_search.cv_results_['mean_test_score'])
                print('training scores:'  , clf_search.cv_results_['mean_train_score'])
            res.append((clf_search.best_estimator_, clf_search.best_score_, time_grid, time_fit))
        except Exception as e:
            if verbose: traceback.print_exc()
            res.append((clf_Klass(), -np.inf, np.inf, np.inf))
    print('='*72)
    print(tabulate([[m.__class__.__name__, '%.3f'%s, '%.0f'%time_grid, '%.3f'%time_fit] for m, s, time_grid, time_fit in res], headers=['Model', scoring, 'Time/grid (s)', 'Time/clf (s)']))
    winner_ind = np.argmax([v[1] for v in res])
    winner = res[winner_ind][0]
    print('='*72)
    print('The winner is: %s with score %0.3f.' % (winner.__class__.__name__, res[winner_ind][1]))
    return winner, res



if __name__ == '__main__':
    y = np.array([0,1,0,0,0,3,1,1,3])
    x = np.zeros(len(y))
    for t, v in cv_reg(x): print(v,t)
    for t, v in cv_clf(x, y, test_size=5): print(v,t)