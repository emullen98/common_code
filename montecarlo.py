# -*- coding: utf-8 -*-
"""
Created on Fri Jul  5 14:23:05 2024
#include all the monte-carlo estimators (i.e. find_pl_montecarlo), finding p value thresholds, etc.
"""
import numba
import numpy as np
from .distances import find_d_sorted, find_ad_sorted, find_nearest_idx, find_d_sorted_discrete,find_nearest_idx_discrete
from .brent import brent_findmin, brent_findmin_discrete
from .likelihoods import pl_gen

arr = np.array

#used to estimate the pq value from D in the monte carlo xmin/xmax. 10 terms is plenty to get extremely high accuracy.
@numba.njit
def expfun(x,numterms = 10):
    val = 0
    for i in range(1,numterms+1):
        val = val + (-1)**(i-1)*np.exp(-2* i**2 * x**2)
        
    return 2*val

#find the true p value (as compared to pq). See Deluca & Corrall 2013 (https://doi.org/10.2478/s11600-013-0154-9).
#If true p > 0.15 (or maybe p > 0.2), then the power law fit is good.

#wrapper for accessing find_p from common_code. Does not need to be sorted.
def find_p_wrap(x,xmin,xmax, runs = 150, discrete = False):
    """
    Find the p value of a given range of xmin/xmax via  KS distance simulation. See Deluca & Corrall 2013 (https://doi.org/10.2478/s11600-013-0154-9).
    
    :param np.array x: The data to find the scaling regime over.
    :param float xmin: Minimum of the scaling regime to test.
    :param float xmax: Maximum of the scaling regime to test.
    :param float runs: Number of runs to estimate the p-value for. Default is 150, which gives the correct p-value within ~10%.
    :param bool discrete: Whether to use the continuous or discrete version of find_p. Default False.
    
    
    """
    if discrete == False:
        return find_true_p(np.sort(x),xmin,xmax, runs, find_d_sorted)
    
    print("error. Discrete not implemented yet.")
    return -1
    

@numba.njit
def find_true_p(x,xmin,xmax,runs = 150, dfun = find_d_sorted):
    
    tot = 0
    p = 1
    sigp = 0
    xmin_idx = find_nearest_idx(x,xmin)
    xmax_idx = find_nearest_idx(x,xmax)
    x = x[xmin_idx:xmax_idx + 1]
    n = len(x)
    alpha = brent_findmin(x)
    de = dfun(x,alpha)
    for i in range(runs):
        synth = np.sort(pl_gen(n,xmin,xmax,alpha))
        asynth = brent_findmin(synth)
        ds = dfun(synth,asynth)
        if ds >= de:
            tot = tot + 1
        #tot = tot + (ds >= de) #if ds > de, increment tot
        
    p = tot/runs
    sigp = np.sqrt(p*(1-p)/runs) #1 sigma (68% CI)
    
    return p,sigp
#core of the find_p part of the montecarlo code. Broken into its own jitted function to improve overhead in communicating between C and Python.
#very minimal speed increase (<10%) compared to python implementation.
@numba.njit(parallel = True)
def find_p_core(data,possible_xmins,possible_xmaxs, pruns, dfun):
    possible_ps = np.zeros(len(possible_xmins))
    for i in numba.prange(len(possible_ps)):
        xmin = possible_xmins[i]
        xmax = possible_xmaxs[i]
        xmin_idx = find_nearest_idx(data,xmin)
        xmax_idx = find_nearest_idx(data,xmax)
        trimmed = data[xmin_idx:xmax_idx + 1]
        possible_ps[i] = find_true_p(trimmed,xmin,xmax, runs = pruns, dfun = dfun)[0]
    
    return possible_ps
        
    
#use a monte carlo approach of finding xmin, xmax, and alpha using AD statistic. Parallelization and njit() has improved speed to ~600 ms per star with these options.
def find_pl_montecarlo(data, runs = 2000, pqcrit = 0.35, pcrit = 0.25, pruns = 100, dist_type = 'AD', calc_p = True):
    """
    Find the best xmin and xmax for a power law scaling regime in data using a monte-carlo approach.
    The approach works by quantifying the KS (or AD) distance for many choices of xmin/xmax and
    usiung the maximum likelihood estimated alpha, from [1]. Then, a 'fake' p-value (pq) is generated
    using a simple (but incorrect) formula in terms of the KS distance which always overestimates the
    true p value[1,2]. All runs with pq > pqcrit are labeled as candidate runs. Then, for each
    candidate runs, pruns are used to estimate the true p value [1]. The xmin/xmax are chosen as
    those that have p > pcrit and have the largest value of xmax/xmin.
    
    TODO:
        --Work to derive a function for calculating 'fake' pq from AD value. Relies on quadratic statistics
        --Obtain method against biasing values of xmax that are too high
        --Obtain method for estimating confidence intervals on estimated xmin and xmax.
    
    Sources
    [1] Deluca & Corrall 2013 (https://doi.org/10.2478/s11600-013-0154-9).
    [2] DOI: 10.4236/am.2020.113018 by Jan Vrbik 2020 which gives the more accurate formula for false p value from D.

    Parameters
    ----------
    data : array
        An array of data to search for xmin and xmax in. If using the 'discrete' option, must be normalized to the timestep dt before being input.
    runs : int, optional
        The number of monte-carlo runs to use to find the best xmin/xmax pair. A fake pq value is generated for each of these pairs of xmin/xmax. Good results are generally found with runs > 1000, but generally runs > 20000 is not needed. The default is 2000.
    pqcrit : float, optional
        The value of the 'fake' p value, pq, that the scaling regime between xmin/xmax must
        be higher than to be considered possible. 0 < pqcrit < 1, and the higher pq is, the 
        more strict the choice is at the cost of throwing out many usually very good runs.
        Good performance is generally obtained with 0.2 < pqcrit < 0.5.
        
        pqcrit is used as an initial sieve to initially throw out bad choices of xmin/xmax
        because calculating the 'true' p value is far more computationally costly and is
        always less than pq. The default is 0.35.
    pcrit : float, optional
        The value of the 'true' p value that the scaling regime between xmin/xmax must be
        higher than to be considered possible. 0 < pcrit < 1, and higher is more strict
        at the cost of throwing out many usually very good runs. Good performance is
        generally obtained with 0.15 < pcrit < 0.35. The default is 0.25.
    pruns : float, optional
        The number of runs per pair of xmin/xmax with pq > pqcrit used to calculate the
        'true' p-value. pruns should be at least 100, but much higher is generally not 
        worth the computational cost since the relative error is at worst 10% at pruns =
        100. The default is 100.
    dist_type : string, optional
        The type of distribution to calculate the 'D' metric with. Use 'KS' for the 
        Kolmogorov-Smirnov distance, 'AD' for the Anderson-Darling distance, and 'discrete'
        for the discrete KS distance. AD distance is generally slightly better than KS, but
        the computational cost is higher. However, KS distance performs mostly just as well
        on test data. The 'discrete' case always uses the discrete KS distance. The default 
        is 'AD'.
    calc_p : boolean, optional
        If True, calculates the p value. Otherwise, sets p threshold to the pq threshold, so
        p is not calculated in an effort to save time. The default is True.

    Returns
    -------
    xmin: float
        The minimum of the scaling regime.
    xmax: float
        The maximum of the scaling regime.
    alpha: float
        The optimal alpha found.
    """
    
    data = np.sort(data) 
    dfun = find_d_sorted
    distfun = find_d_sorted
    brent = brent_findmin
    nearest_first = find_nearest_idx
    nearest_last = find_nearest_idx
    
    defaults = [0,0,1]
    if calc_p == False:
        pcrit = pqcrit
        
    if dist_type == 'KS':
        distfun = find_d_sorted
        dfun = find_d_sorted
        brent = brent_findmin
        nearest_first = find_nearest_idx
        nearest_last = find_nearest_idx
    elif dist_type == 'AD':
        distfun = find_ad_sorted
    elif dist_type == 'discrete':
        distfun = find_d_sorted_discrete
        dfun = find_d_sorted_discrete
        brent = brent_findmin_discrete
        nearest_first = lambda x,val : find_nearest_idx_discrete(x,val,1)
        nearest_last = lambda x,val : find_nearest_idx_discrete(x,val,0)
        if np.any(data < 1):
            print('Error. Please ensure data is discretized in terms of step size before using discrete option. Returning.')
            return defaults
    else:
        print('Error. Please input a valid distance type (either KS, AD, or discrete)')
        return defaults

    #NOTE: due to a bug in numba (conditional statements don't work in for loops), we cannot compile this core function to njit.
    attempted_xmins = np.ones(runs)
    attempted_xmaxs = np.ones(runs)
    attempted_alphas = np.ones(runs)
    attempted_ns = np.ones(runs)
    attempted_pqs = np.ones(runs)
    attempted_ds = 1e12*np.ones(runs)
    log_xmin = np.log(data[0])
    log_xmax = np.log(data[-1])
    log_range = log_xmax-log_xmin
    trial_xmin = 0
    trial_xmax = 0
    trial_xmin_idx = 0
    trial_xmax_idx = 0
    for i in range(runs):
        trial_xmin = np.exp(log_xmin + log_range*np.random.rand())
        trial_xmax = np.exp(log_xmin + log_range*np.random.rand())
        trial_xmin_idx = nearest_first(data,trial_xmin)
        trial_xmax_idx = nearest_last(data,trial_xmax)
        trial_xmin = data[trial_xmin_idx]
        trial_xmax = data[trial_xmax_idx]
        
        #ensure there are at least 10 datapoints and that xmax > 2*xmin
        #the comparison in the while loop is what ruins being able to njit this function. It cannot be replaced by anything that has a conditional in it.
        while (trial_xmax_idx - trial_xmin_idx < 10) or (trial_xmax < 2*trial_xmin):
            trial_xmin = np.exp(log_xmin + log_range*np.random.rand())
            trial_xmax = np.exp(log_xmin + log_range*np.random.rand())
            trial_xmin_idx = nearest_first(data,trial_xmin)
            trial_xmax_idx = nearest_last(data,trial_xmax)
            trial_xmin = data[trial_xmin_idx]
            trial_xmax = data[trial_xmax_idx]
        trimmed = data[trial_xmin_idx:trial_xmax_idx+1]
        alpha_hat = brent(trimmed)
        tmpd = 1
        if alpha_hat > 1:
            attempted_ds[i] = distfun(trimmed,alpha_hat)
            tmpd = dfun(trimmed,alpha_hat)
        n = len(trimmed)
        
        
        #Function is Equation 29 in Deluca & Corrall 2013 (https://doi.org/10.2478/s11600-013-0154-9)
        #and is given on the wikipedia article on the KS test. According to Deluca & Corrall 2013, this only weakly correlates with the true p value.
        #this is obtained by noting that expfun(z) is distributed according to the expfun distribution if one sets z = np.sqrt(z)*d + (correction factors).
        #attempted_pqs[i] = expfun(tmpd*np.sqrt(n) + 0.12*tmpd + 0.11*tmpd/np.sqrt(n))
        
        #By first converting d --> d*np.sqrt(n), then we use the updated term from DOI: 10.4236/am.2020.113018 by Jan Vrbik 2020 (much more accurate)
        tmpd = tmpd*np.sqrt(n) 
        attempted_pqs[i] = expfun(tmpd + 0.17/np.sqrt(n) + (tmpd - 1)/(4*n))
        attempted_ns[i] = n
        attempted_alphas[i] = alpha_hat
        attempted_xmins[i] = trial_xmin
        attempted_xmaxs[i] = trial_xmax
    
    
    #find the possible indices. For each possible index, calculate the true p value using simulation.
    idxs = np.where(attempted_pqs > pqcrit)[0]
    
    #edge case: if none of the fits are good enough, return the xmin,xmax where pq is the highest
    if len(idxs) == 0:
        minidx = np.argmax(attempted_pqs)
        xmin = attempted_xmins[minidx]
        xmax = attempted_xmaxs[minidx]
        alpha = attempted_alphas[minidx]
        pq = attempted_pqs[minidx]
        p = attempted_pqs[minidx]
        return xmin,xmax,alpha
        
    possible_xmins = attempted_xmins[idxs]
    possible_xmaxs = attempted_xmaxs[idxs]
    possible_alphas = attempted_alphas[idxs]
    possible_pqs = attempted_pqs[idxs]
    #print(len(possible_pqs))
    
    
        
    possible_ps = np.zeros(len(possible_pqs))
    if calc_p == True:
        possible_ps = find_p_core(data,possible_xmins,possible_xmaxs, pruns, dfun)
    else:
        possible_ps = possible_pqs
    
    #only examine runs where the p-value is greater than the pcrit (default 0.2)
    idxs2 = np.where(possible_ps > pcrit)[0]

    #edge case: if none of the fits are good enough, return the xmin,xmax where pq is the highest
    if len(idxs2) == 0:
        minidx = np.argmax(possible_ps)
        xmin = possible_xmins[minidx]
        xmax = possible_xmaxs[minidx]
        alpha = possible_alphas[minidx]
        pq = possible_pqs[minidx]
        p = possible_ps[minidx]
        return xmin,xmax,alpha
    
    possible_xmins2 = possible_xmins[idxs2]
    possible_xmaxs2 = possible_xmaxs[idxs2]
    possible_alphas2 = possible_alphas[idxs2]
    possible_pqs2 = possible_pqs[idxs2]
    possible_ps2 = possible_ps[idxs2]
    
    minidx = np.argmax(possible_xmaxs2/possible_xmins2)
    
    xmin = possible_xmins2[minidx]
    xmax = possible_xmaxs2[minidx]
    alpha = possible_alphas2[minidx]
    
    #the "false" p-value from equation 29 of (https://doi.org/10.2478/s11600-013-0154-9).
    pq = possible_pqs2[minidx]
    p = possible_ps2[minidx]
    

    return xmin,xmax,alpha