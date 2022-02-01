#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
"""
Created on Fri May 01 2020

@author: thopri
example usage: (in python console)
from pynemo.tides import nemo_tide_test as tt
tt.main()

conda install xlsxwriter pandas
python pynemo/tests/nemo_tide_test.py


all parameters have defaults applied if not supplied:
location of bdy file - 'inputs/namelist_cmems.bdy'
amplitude threshold - 0.25 m
phase threshold - 10.00 degrees
model resolution - 1/16 degree
model - 'fes'

So for FES the only model currently supported only the location of the BDY file and thresholds (if different from defaults)
need to be provided. For TPXO this would vary based on the resolution e.g. TPXO7.2 is 1/4 and 'tpxo'

The script generates a excel spreadsheet that contains the locations and amplitudes and phases for all HC's
defined in the bdy file that exceed the default or defined the thresholds passed to the main function.
File locations e.g. model reference location etc are all taken from bdy file that is passed to the main function

To do this the script compiles a list of PyNEMO boundary amplitudes and phases and lat/lon's, finds the closest value
in the reference model (currently only FES is supported), and then compares them. If the absolute difference is greater
than defined threshold then the location and parameter (either Amp or Phase) is returned within a Pandas Dataframe
which is then written to a spreadsheet.

Notes:
The script checks the Amplitude and Phase independently, so lat/lons for each are also returned. Each HC is saved to
a separate sheet in the spreadsheet. The name of the spreadsheet contains meta data showing thresholds and reference
model used. Units for threshold are meters and degrees.

Update: fill values for FES are commonly returned at coastlines, this is due to the nearest FES cell being land but PyNEMO
will have interpolated data from the water. In instance the code checks the cells aroud the fill value and averages both
amplitude and phase (using HsinG,HcosG) to act as a reference.

Phase threshold is not longer required as it is applied using an function that references amplitude, the idea is that the
threshold is low for high amplitudes, e.g. 5 degrees for 1.0m and high for low amplitudes 80 degrees for 0.01 m.

Amplitudes at phase exceedance locataions are also returned to allow assessment of the impact, e.g. low amplitude low impact

"""
from netCDF4 import Dataset
import numpy as np
import logging
import time
import pandas as pd
import warnings
from pynemo import nemo_bdy_setup as setup

# log to PyNEMO log file
logger = logging.getLogger(__name__)
logging.basicConfig(filename='nrct.log', level=logging.INFO)

# TODO: add TPXO read and subset functionality currently only uses FES as "truth"

def main(bdy_file='inputs/namelist_local.bdy',model='fes'):
    logger.info('============================================')
    logger.info('Start Tide Test Logging: ' + time.asctime())
    logger.info('============================================')
    # get settings dict based on bdy file
    Setup = setup.Setup(bdy_file)  # default settings file
    settings = Setup.settings
    constituents = settings['clname']
    # TODO maybe define Z and/or UV in bdy file? at the moment Z, U and Vs are generated with no option for Z only.
    grids = ['Z']#,'U','V']
    if model == 'fes':
        logger.info('using FES as reference.......')
        # open writer object to write pandas dataframes to spreadsheet
        writer = pd.ExcelWriter(settings['dst_dir'] + 'comparision_with_'+str(model)+'.xlsx', engine='xlsxwriter')
        for key in constituents:
            for j in range(len(grids)):
                out_fname = settings['dst_dir']+settings['fn']+'_bdytide_'+constituents[key].strip("',/\n")+'_grd_'+grids[j]+'.nc'
                logger.info('processing output file '+out_fname)
                #fes_fname = settings['tide_fes']+constituents[key].strip("',/\n")+'_'+grids[j]+'.nc'
                fes_fname = settings['tide_fes']+"ocean_tide_extrapolated/"+constituents[key].strip("'").lower()+'.nc'
                # read in FES data (whole globe)
                fes = read_fes(fes_fname, grids[j])
                grid = grids[j].lower()
                # extract PyNEMO data from output files (generate list of lats,lons etc)
                pynemo_out = extract_PyNEMO_output(out_fname, grid)
                # subset FES to match PyNEMO list of lat lons
                subset_fes = subset_reference(pynemo_out, fes)
                # compare the two lists (or dicts really)
                error_log = compare_tides(pynemo_out, subset_fes)
                # return differences above threshold as a Pandas Dataframe and name using HC and Grid
                error_log.name = constituents[key].strip("',/\n") + grids[j]
                # if the dataframe is empty (no exceedances) then discard dataframe and log the good news
                if error_log.empty == True:
                    logger.info('output file does not exceed threshold when compared with reference model..... thats good!')
                # if dataframe has values then these exceed the threshold, log and save to excel spreadsheet using dataset
                # name e.g. M2Z (based on HC and grid) as name for the sheet
                if error_log.empty == False:
                    logger.warning('Exceedance in thesholds detected, check spreadsheet in dst_dir')
                    error_log.to_excel(writer,sheet_name=error_log.name)
                # close writer object and save excel spreadsheet
        writer.save()
    # code runs here if TPXO is requested as reference this hasn't been written yet so raises exception
    elif model == 'tpxo':
        logger.info('using TPXO as reference.......')
        logger.exception('not set up to use TPXO yet...... exiting')
        raise Exception('Not setup for TPXO use FES instead?')
    # everything else goes here which shouldn't happen so is raised as an exception
    else:
        logger.exception('Tide reference model not recognised.... exiting')
        raise Exception('Invalid tide referece model name provided')
    return 0

    # find nearest value in array used for finding subset of Lat and Lon
def find_nearest(array, value):
    array = np.asarray(array)
    idx = (np.abs(array - value)).argmin()
    return idx

    # extract PyNEMO output from netcdf file, convert HcosG and HsinG to Amp and Phase
    # and extract lons and lats from I and J coords. return a dict
def extract_PyNEMO_output(out_fname,grid):
    tide_out = Dataset(out_fname)
    nav_lat = tide_out.variables['nav_lat'][:]
    nav_lon = tide_out.variables['nav_lon'][:]
    nbidta = tide_out.variables['nbidta'][:]
    nbjdta = tide_out.variables['nbjdta'][:]
    cosine = np.array(tide_out.variables[grid+'1'][:])
    sine = np.array(tide_out.variables[grid+'2'][:])
    amp = np.hypot(sine,cosine)
    phase = np.arctan2(sine[0,:],cosine[0,:])
    phase = np.degrees(phase)
    lat = np.array(nav_lat[nbjdta, nbidta])
    lon = np.array(nav_lon[nbjdta, nbidta])
    pynemo_out = {'lat':lat,'lon':lon,'amp':amp,'phase':phase}
    tide_out.close()
    return pynemo_out

    # read FES netcdf file, convert lon to -180 to 180, rather than 0-360 it also converts amplitude from CM to M
    # return a dict
def read_fes(fes_fname,grid):
    fes_tide = Dataset(fes_fname)
    if grid == 'Z':
        fes_amp = np.array(fes_tide.variables['amplitude'][:])
        # convert to m
        fes_amp = fes_amp / 100
        fes_phase = np.array(fes_tide.variables['phase'][:])

    if grid != 'Z':
        fes_amp = np.array(fes_tide.variables[grid+'a'][:])
        fes_phase = np.array(fes_tide.variables[grid+'g'][:])
        # convert to m/s
        fes_amp = fes_amp/100

    fes_lat = fes_tide.variables['lat'][:]
    fes_lon = fes_tide.variables['lon'][:]
    # change to -180 to 180 lonitude convention
    fes_lon[fes_lon > 180.0] = fes_lon[fes_lon > 180.0] - 360.0
    fes_dict = {'lat':fes_lat,'lon':fes_lon,'amp':fes_amp,'phase':fes_phase}
    fes_tide.close()
    return fes_dict

    # subset FES dict from read_FES, this uses find_nearest to find nearest FES point using PyNEMO dict from extract_PyNEMO
    # It also converts FES amplitude from cm to m.
def subset_reference(pynemo_out, reference):
    model_res = np.abs(reference['lon'][0]-reference['lon'][1])
    idx_lat = np.zeros(np.shape(pynemo_out['lat']))
    for i in range(np.shape(pynemo_out['lat'])[1]):
        idx_lat[0, i] = find_nearest(reference['lat'], pynemo_out['lat'][0, i])
    idx_lat = idx_lat.astype(np.int64)

    idx_lon = np.zeros(np.shape(pynemo_out['lon']))
    for i in range(np.shape(pynemo_out['lon'])[1]):
        idx_lon[0, i] = find_nearest(reference['lon'], pynemo_out['lon'][0, i])
    idx_lon = idx_lon.astype(np.int64)

    amp_sub = reference['amp'][idx_lat, idx_lon]
    # surpress warnings due to NaNmean
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for i in range(np.shape(amp_sub)[1]):
            # if a fill value in FES subset is found
            if amp_sub[0, i] == 184467436613926912.0000:
                logger.warning('found fill value in FES subset, taking nanmean from surrounding amplitude points')
                # if there are fill values surrounding subset fill value change these to NaN
                if reference['amp'][idx_lat[0,i]+1, idx_lon[0,i]]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]] = np.nan
                if reference['amp'][idx_lat[0,i], idx_lon[0,i]+1]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i], idx_lon[0,i]+1] = np.nan
                if reference['amp'][idx_lat[0,i]-1, idx_lon[0,i]]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]] = np.nan
                if reference['amp'][idx_lat[0,i], idx_lon[0,i]-1]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i], idx_lon[0, i]-1] = np.nan
                if reference['amp'][idx_lat[0,i]+1, idx_lon[0,i]+1]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]+1] = np.nan
                if reference['amp'][idx_lat[0,i]-1, idx_lon[0,i]-1]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]-1] = np.nan
                if reference['amp'][idx_lat[0,i]-1, idx_lon[0,i]+1]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]+1] = np.nan
                if reference['amp'][idx_lat[0,i]+1, idx_lon[0,i]-1]== 184467436613926912.0000:
                    reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]-1] = np.nan
                # nan mean surrounding points to replace fill value subset point
                amp_sub[0,i] = np.nanmean([reference['amp'][idx_lat[0,i]+1, idx_lon[0,i]], \
                              reference['amp'][idx_lat[0,i], idx_lon[0,i]+1], \
                              reference['amp'][idx_lat[0,i]-1, idx_lon[0,i]], \
                              reference['amp'][idx_lat[0,i], idx_lon[0,i]-1], \
                              reference['amp'][idx_lat[0,i]+1, idx_lon[0,i]]+1, \
                              reference['amp'][idx_lat[0,i]-1, idx_lon[0,i]-1], \
                              reference['amp'][idx_lat[0,i]-1, idx_lon[0,i]+1], \
                              reference['amp'][idx_lat[0,i]+1, idx_lon[0,i]-1] \
                                           ])
        phase_sub = reference['phase'][idx_lat, idx_lon]
        for i in range(np.shape(phase_sub)[1]):
            # if a fill value in FES subset is found
            if phase_sub[0, i] == 18446744073709551616.0000:
                logger.warning('found fill value in FES subset, taking nanmean from surrounding phase points')
                # if there are fill values surrounding subset fill value change these to NaN
                if reference['phase'][idx_lat[0, i] + 1, idx_lon[0, i]] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i] + 1, idx_lon[0, i]] = np.nan
                if reference['phase'][idx_lat[0, i], idx_lon[0, i] + 1] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i], idx_lon[0, i] + 1] = np.nan
                if reference['phase'][idx_lat[0, i] - 1, idx_lon[0, i]] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i] - 1, idx_lon[0, i]] = np.nan
                if reference['phase'][idx_lat[0, i], idx_lon[0, i] - 1] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i], idx_lon[0, i] - 1] = np.nan
                if reference['phase'][idx_lat[0, i] + 1, idx_lon[0, i] + 1] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i] + 1, idx_lon[0, i] + 1] = np.nan
                if reference['phase'][idx_lat[0, i] - 1, idx_lon[0, i] - 1] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i] - 1, idx_lon[0, i] - 1] = np.nan
                if reference['phase'][idx_lat[0, i] - 1, idx_lon[0, i] + 1] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i] - 1, idx_lon[0, i] + 1] = np.nan
                if reference['phase'][idx_lat[0, i] + 1, idx_lon[0, i] - 1] == 18446744073709551616.0000:
                    reference['phase'][idx_lat[0, i] + 1, idx_lon[0, i] - 1] = np.nan
                # calculate HcosG and then average
                HcosG = np.nanmean([reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]]*np.cos(
                             reference['phase'][idx_lat[0, i]+1, idx_lon[0, i]]*np.pi/180),
                         reference['amp'][idx_lat[0, i], idx_lon[0, i]+1] * np.cos(
                             reference['phase'][idx_lat[0, i], idx_lon[0, i]+1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]] * np.cos(
                             reference['phase'][idx_lat[0, i]-1, idx_lon[0, i]] * np.pi / 180),
                         reference['amp'][idx_lat[0, i], idx_lon[0, i]-1] * np.cos(
                             reference['phase'][idx_lat[0, i], idx_lon[0, i]-1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]+1] * np.cos(
                             reference['phase'][idx_lat[0, i]+1, idx_lon[0, i]+1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]-1] * np.cos(
                             reference['phase'][idx_lat[0, i]-1, idx_lon[0, i]-1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]+1] * np.cos(
                             reference['phase'][idx_lat[0, i]-1, idx_lon[0, i]+1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]-1] * np.cos(
                             reference['phase'][idx_lat[0, i]+1, idx_lon[0, i]-1] * np.pi / 180),
                         ])
                # calculate HsinG and then average
                HsinG = np.nanmean([reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]]*np.sin(
                             reference['phase'][idx_lat[0, i]+1, idx_lon[0, i]]*np.pi/180),
                         reference['amp'][idx_lat[0, i], idx_lon[0, i]+1] * np.sin(
                             reference['phase'][idx_lat[0, i], idx_lon[0, i]+1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]] * np.sin(
                             reference['phase'][idx_lat[0, i]-1, idx_lon[0, i]] * np.pi / 180),
                         reference['amp'][idx_lat[0, i], idx_lon[0, i]-1] * np.sin(
                             reference['phase'][idx_lat[0, i], idx_lon[0, i]-1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]+1] * np.sin(
                             reference['phase'][idx_lat[0, i]+1, idx_lon[0, i]+1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]-1] * np.sin(
                             reference['phase'][idx_lat[0, i]-1, idx_lon[0, i]-1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]-1, idx_lon[0, i]+1] * np.sin(
                             reference['phase'][idx_lat[0, i]-1, idx_lon[0, i]+1] * np.pi / 180),
                         reference['amp'][idx_lat[0, i]+1, idx_lon[0, i]-1] * np.sin(
                             reference['phase'][idx_lat[0, i]+1, idx_lon[0, i]-1] * np.pi / 180),
                         ])
                # convert back to phase
                phase_sub[0,i] = np.arctan2(HsinG,HcosG)

    lat_sub = reference['lat'][idx_lat]
    lon_sub = reference['lon'][idx_lon]
    subset = {'lat':lat_sub,'lon':lon_sub,'amp':amp_sub,'phase':phase_sub,'model_res':model_res}
    return subset

    # takes pynemo extract dict, subset fes dict, and the thresholds and model res passed to main function.
    # returns a Pandas Dataframe with any PyNEMO values that exceed the nearest FES point by defined threshold
    # It also checks lats and lons are within the model reference resolution
    # i.e. ensure closest model reference point is used.
def compare_tides(pynemo_out,subset):
    # compare lat and lons
    diff_lat = np.abs(pynemo_out['lat']-subset['lat'])
    diff_lon = np.abs(pynemo_out['lon'] - subset['lon'])
    exceed_lat = diff_lat > subset['model_res']
    exceed_lon = diff_lon > subset['model_res']
    exceed_sum = np.sum(exceed_lat+exceed_lon)
    if exceed_sum > 0:
        raise Exception('Dont Panic: Lat and/or Lon further away from model point than model resolution')
    # surpress warnings as NaNs from averaging surrounding pixels can cause issues
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        # compare amp
        abs_amp_diff = np.abs(pynemo_out['amp']-subset['amp'])
        # calculate threshold in percentage terms
        logger.info('percentage amplitude exceedance calculated using the following.....')
        amp_percentage_exceed = 26.933 * subset['amp'] ** -0.396
        logger.info('Percentage Exceedance = 26.933 * Reference Amplitude ^ -0.396')
        # work out difference based on percentage and reference amplitude
        percent_diff = (abs_amp_diff / pynemo_out['amp']) * 100
        abs_amp_thres = percent_diff > amp_percentage_exceed
        err_amp = pynemo_out['amp'][abs_amp_thres].tolist()
        err_amp_lats = pynemo_out['lat'][abs_amp_thres].tolist()
        err_amp_lons = pynemo_out['lon'][abs_amp_thres].tolist()

        err_ref_amp = subset['amp'][abs_amp_thres].tolist()
        err_ref_lats_amp = subset['lat'][abs_amp_thres].tolist()
        err_ref_lons_amp = subset['lon'][abs_amp_thres].tolist()

        # compare phase
        # change from -180-180 to 0to 360 for both pynemo and subset.
        pynemo_out['phase'][pynemo_out['phase'] < 0.0] = pynemo_out['phase'][pynemo_out['phase'] < 0.0] + 360.0
        subset['phase'][subset['phase'] < 0.0] = subset['phase'][subset['phase'] < 0.0] + 360.0
        # compare phase angles between 0 and 360.
        abs_ph = 180 - abs(abs(pynemo_out['phase'] - subset['phase']) - 180)
        # values outside of 0 to 360  (such as erroneous fill values) end up negative
        # so multiply by -1 to ensure they are identified as exceeding threshold
        abs_ph[abs_ph < 0.0 ] = abs_ph[abs_ph < 0.0] *-1
        # calculate phase threshold based on amplitude and power relationship
        # as amplitude decreases the phase exceedance allowed increases.
        logger.info('phase exceedance calculated using the following.....')
        phase_thres = 5.052 * pynemo_out['amp'] ** -0.60
        logger.info('Exceedance = 5.052 * Amplitude ^ -0.60')
        abs_ph_thres = abs_ph > phase_thres

        err_pha = pynemo_out['phase'][abs_ph_thres[0,:]].tolist()
        err_pha_amp = pynemo_out['amp'][abs_ph_thres].tolist()
        err_pha_lats = pynemo_out['lat'][abs_ph_thres].tolist()
        err_pha_lons = pynemo_out['lon'][abs_ph_thres].tolist()

        err_ref_pha = subset['phase'][abs_ph_thres].tolist()
        err_ref_pha_amp = subset['amp'][abs_ph_thres].tolist()
        err_ref_lats_pha = subset['lat'][abs_ph_thres].tolist()
        err_ref_lons_pha = subset['lon'][abs_ph_thres].tolist()

        lerr_pha, lerr_amp = len(err_pha), len(err_amp)
        max_len = max(lerr_pha, lerr_amp)
        if not max_len == lerr_pha:
            err_pha.extend([''] * (max_len - lerr_pha))
            err_pha_amp.extend([''] * (max_len - lerr_pha))
            err_pha_lats.extend([''] * (max_len - lerr_pha))
            err_pha_lons.extend([''] * (max_len - lerr_pha))
            err_ref_pha.extend([''] * (max_len - lerr_pha))
            err_ref_pha_amp.extend([''] * (max_len - lerr_pha))
            err_ref_lats_pha.extend([''] * (max_len - lerr_pha))
            err_ref_lons_pha.extend([''] * (max_len - lerr_pha))
        if not max_len == lerr_amp:
            err_amp.extend([''] * (max_len - lerr_amp))
            err_amp_lats.extend([''] * (max_len - lerr_amp))
            err_amp_lons.extend([''] * (max_len - lerr_amp))
            err_ref_amp.extend([''] * (max_len - lerr_amp))
            err_ref_lats_amp.extend([''] * (max_len - lerr_amp))
            err_ref_lons_amp.extend([''] * (max_len - lerr_amp))

        err_log = pd.DataFrame({'amp_lat':err_amp_lats,
                                'amp_lon':err_amp_lons,
                                'amp':err_amp,
                                'ref_amp': err_ref_amp,
                                'ref_amp_lats': err_ref_lats_amp,
                                'ref_amp_lons': err_ref_lons_amp,
                                'phase_lat':err_pha_lats,
                                'phase_lon':err_pha_lons,
                                'phase':err_pha,
                                'phase_amp':err_pha_amp,
                                'ref_phase':err_ref_pha,
                                'ref_phase_amp':err_ref_pha_amp,
                                'ref_phase_lats':err_ref_lats_pha,
                                'ref_phase_lons':err_ref_lons_pha
                                })

    return err_log

if __name__ == '__main__':
    main()





