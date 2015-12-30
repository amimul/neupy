import math

import theano
import theano.tensor as T
from theano.ifelse import ifelse
import numpy as np
from scipy.optimize import minimize_scalar

from neupy.utils import asfloat
from neupy.core.properties import (BoundedProperty, ChoiceProperty,
                                   IntProperty)
from .base import LearningRateConfigurable


__all__ = ('LinearSearch',)


def interval_location(f, minstep=1e-5, maxstep=50., maxiter=1024):
    """ Identify interval where potentialy could be optimal step.

    Parameters
    ----------
    f : func
    minstep : float
        Defaults to ``1e-5``.
    maxstep : float
        Defaults to ``50``.
    maxiter : int
        Defaults to ``1024``.
    tol : float
        Defaults to ``1e-5``.

    Returns
    -------
    float
        Right bound of interval where could be optimal step in
        specified direction. In case if there is no such direction
        function return ``maxstep`` instead.
    """

    def find_right_bound(prev_func_output, step, maxstep):
        func_output = f(step)
        is_output_decrease = T.gt(prev_func_output, func_output)
        step = ifelse(
            is_output_decrease,
            T.minimum(2. * step, maxstep),
            step
        )

        is_output_increse = T.lt(prev_func_output, func_output)
        stoprule = theano.scan_module.until(
            T.or_(is_output_increse, step > maxstep)
        )
        return [func_output, step], stoprule

    (_, steps), _ = theano.scan(
        find_right_bound,
        outputs_info=[T.constant(asfloat(np.inf)),
                      T.constant(asfloat(minstep))],
        non_sequences=[maxstep],
        n_steps=maxiter
    )
    return steps[-1]


def golden_search(f, maxstep=50, maxiter=1024, tol=1e-5):
    """ Identify best step for function in specific direction.

    Parameters
    ----------
    f : func
    maxstep : float
        Defaults to ``50``.
    maxiter : int
        Defaults to ``1024``.
    tol : float
        Defaults to ``1e-5``.

    Returns
    -------
    float
        Identified optimal step.
    """

    golden_ratio = asfloat((math.sqrt(5) - 1) / 2)

    def interval_reduction(a, b, c, d, tol):
        fc = f(c)
        fd = f(d)

        a, b, c, d = ifelse(
            T.lt(fc, fd),
            [a, d, d - golden_ratio * (d - a), c],
            [c, b, d, c + golden_ratio * (b - c)]
        )

        stoprule = theano.scan_module.until(
            T.lt(T.abs_(c - d), tol)
        )
        return [a, b, c, d], stoprule

    a = T.constant(asfloat(0))
    b = maxstep
    c = b - golden_ratio * (b - a)
    d = a + golden_ratio * (b - a)

    (a, b, c, d), _ = theano.scan(
        interval_reduction,
        outputs_info=[a, b, c, d],
        non_sequences=[asfloat(tol)],
        n_steps=maxiter
    )
    return (a[-1] + b[-1]) / 2


def fmin_golden_search(f, minstep=1e-5, maxstep=50., maxiter=1024, tol=1e-5):
    """ Minimize scalar function using Golden Search.

    Parameters
    ----------
    f : func
        Function that needs to be minimized. Function need to
        return the scalar.
    minstep : float
        Defaults to ``1e-5``.
    maxstep : float
        Defaults to ``50``.
    maxiter : int
        Defaults to ``1024``.
    tol : float
        Defaults to ``1e-5``.

    Returns
    -------
    object
        Returns the Theano instance that finally should produce
        best possbile step for specified function.
    """
    params = (
        ('maxiter', maxiter),
        ('minstep', minstep),
        ('maxstep', maxstep),
        ('tol', tol),
    )
    for param_name, param_value in params:
        if param_value <= 0:
            raise ValueError("Parameter `{}` should be greater than zero."
                             "".format(param_name))

    if minstep >= maxstep:
        raise ValueError("`minstep` should be smaller than `maxstep`")

    maxstep = interval_location(f, minstep, maxstep, maxiter)
    best_step = golden_search(f, maxstep, maxiter, tol)

    return best_step


class LinearSearch(LearningRateConfigurable):
    """ Linear search for the step selection. Basicly this algorithms
    try different steps and compute your predicted error, after few
    iteration it will chose one which was better.

    Parameters
    ----------
    tol : float
        Tolerance for termination, default to ``0.1``. Can be any number
        greater that zero.
    search_method : 'gloden', 'brent'
        Linear search method. Can be ``golden`` for golden search or ``brent``
        for Brent's search, default to ``golden``.

    Warns
    -----
    {LearningRateConfigurable.Warns}

    Examples
    --------
    >>> import numpy as np
    >>> np.random.seed(0)
    >>>
    >>> from sklearn import datasets, preprocessing
    >>> from sklearn.cross_validation import train_test_split
    >>> from neupy import algorithms, layers
    >>> from neupy.functions import rmsle
    >>>
    >>> dataset = datasets.load_boston()
    >>> data, target = dataset.data, dataset.target
    >>>
    >>> data_scaler = preprocessing.MinMaxScaler()
    >>> target_scaler = preprocessing.MinMaxScaler()
    >>>
    >>> x_train, x_test, y_train, y_test = train_test_split(
    ...     data_scaler.fit_transform(data),
    ...     target_scaler.fit_transform(target),
    ...     train_size=0.85
    ... )
    >>>
    >>> cgnet = algorithms.ConjugateGradient(
    ...     connection=[
    ...         layers.Sigmoid(13),
    ...         layers.Sigmoid(50),
    ...         layers.Output(1),
    ...     ],
    ...     search_method='golden',
    ...     optimizations=[algorithms.LinearSearch],
    ...     verbose=False
    ... )
    >>>
    >>> cgnet.train(x_train, y_train, epochs=100)
    >>> y_predict = cgnet.predict(x_test)
    >>>
    >>> real = target_scaler.inverse_transform(y_test)
    >>> predicted = target_scaler.inverse_transform(y_predict)
    >>>
    >>> error = rmsle(real, predicted.round(1))
    >>> error
    0.20752676697596578

    See Also
    --------
    :network:`ConjugateGradient`
    """

    tol = BoundedProperty(default=0.1, minval=0)
    maxiter = IntProperty(default=1024, minval=1)
    search_method = ChoiceProperty(choices=['golden', 'brent'],
                                   default='golden')

    def train_epoch(self, input_train, target_train):
        weights = [layer.weight.get_value() for layer in self.train_layers]
        train_epoch = self.methods.train_epoch
        shared_step = self.variables.step

        params = [param for param, _ in self.init_train_updates()]
        param_defaults = [param.get_value() for param in params]

        def setup_new_step(new_step):
            for param_default, param in zip(param_defaults, params):
                param.set_value(param_default)

            self.variables.step.set_value(new_step)
            train_epoch(input_train, target_train)
            error = self.methods.prediction_error(input_train, target_train)

            return np.where(np.isnan(error), np.inf, error)

        res = minimize_scalar(
            setup_new_step,
            tol=self.tol,
            method=self.search_method,
            options={'xtol': self.tol, 'maxiter': self.maxiter},
        )

        return setup_new_step(res.x)
