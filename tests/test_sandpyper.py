#!/usr/bin/env python

"""Tests for `sandpyper` package."""


import unittest
import os
import numpy as np
import geopandas as gpd
import pandas as pd
from sandpyper.profile import extract_from_folder
from sandpyper.dynamics import compute_multitemporal
from sandpyper.space import create_transects
from sandpyper.labels import get_sil_location, get_opt_k, kmeans_sa
from sandpyper.outils import coords_to_points, create_details_df
from sandpyper.hotspot import LISA_site_level, Discretiser
import re

pd.options.mode.chained_assignment = None  # default='warn'

# create global variables used across the test analysis
loc_codes=["mar","leo"]
loc_full={'mar': 'Marengo',
         'leo': 'St. Leonards'}
loc_search_dict = {'leo': ['St', 'Leonards', 'leonards', 'leo'], 'mar': ['Marengo', 'marengo', 'mar'] }
crs_dict_string = {'mar': {'init': 'epsg:32754'}, 'leo':{'init': 'epsg:32755'} }

labels=["Undefined", "Small", "Medium", "High", "Extreme"]
appendix=["_deposition", "_erosion"]
relabel_dict={"Undefined_erosion":"ue",
            "Small_erosion":"se",
            "Medium_erosion":"me",
            "High_erosion":"he",
            "Extreme_erosion":"ee",
             "Undefined_deposition":"ud",
             "Small_deposition":"sd",
             "Medium_deposition":"md",
             "High_deposition":"hd",
             "Extreme_deposition":"ed"
            }

if os.getcwdb() != b'C:\\my_packages\\sandpyper\\tests': # if the script is running in github action as a workflow and not locally

    shoreline_leo_path = os.path.abspath("tests/test_data/shorelines/leo_shoreline_short.gpkg")
    shoreline_mar_path = os.path.abspath('tests/test_data/shorelines/mar_shoreline_short.gpkg')
    dsms_dir_path = os.path.abspath('tests/test_data/dsm_1m/')
    orthos_dir_path = os.path.abspath('tests/test_data/orthos_1m')
    transects_path = os.path.abspath('tests/test_data/transects')

else:

    shoreline_leo_path = os.path.abspath("test_data/shorelines/leo_shoreline_short.gpkg")
    shoreline_mar_path = os.path.abspath('test_data/shorelines/mar_shoreline_short.gpkg')
    dsms_dir_path = os.path.abspath('test_data/dsm_1m/')
    orthos_dir_path = os.path.abspath('test_data/orthos_1m/')
    transects_path = os.path.abspath('test_data/transects/')


class TestCreateProfiles(unittest.TestCase):
    """Tests the creation profile function."""

    def setUp(self):
        """Load shorelines examples and create necessary objects"""

        self.leo_shoreline = gpd.read_file(shoreline_leo_path)
        self.mar_shoreline = gpd.read_file(shoreline_mar_path)


    def tearDown(self):
        """Tear down test datasets, if any."""
        self.leo_shoreline
        self.mar_shoreline

    def test_000_CreateTransects(self):
        """Test create transects function."""
        transects_leo=create_transects(self.leo_shoreline,
                           sampling_step=20,
                           tick_length=50,
                           location='leo',
                           crs=crs_dict_string['leo'],
                           side='both'
                          )
        self.assertEqual(transects_leo.shape, (59, 3))
        self.assertEqual(transects_leo.length.mean(), 49.99999999999309)
        self.assertEqual(transects_leo.crs.name, 'WGS 84 / UTM zone 55S')
        self.assertIsInstance(transects_leo,  gpd.GeoDataFrame)


    def test_001_CreateTransects(self):
        transects_mar=create_transects(self.mar_shoreline,
                       sampling_step=20,
                       tick_length=50,
                       location='mar',
                       crs=crs_dict_string['mar'],
                       side='both'
                      )

        self.assertEqual(transects_mar.shape, (27, 3))
        self.assertEqual(transects_mar.length.mean(), 49.999999999999716)
        self.assertEqual(transects_mar.crs.name, 'WGS 84 / UTM zone 54S')
        self.assertIsInstance(transects_mar,  gpd.GeoDataFrame)

    def test_002_CreateTransects(self):
        with self.assertRaises(ValueError) as cm:
            create_transects(self.leo_shoreline,
                           sampling_step=0,
                           tick_length=100,
                           location='leo' ,crs=crs_dict_string['leo'],
                           side='both'
                          )
        the_exception = cm.exception
        print(the_exception)
        self.assertEqual(the_exception.args, ("Maximum allowed size exceeded",))

    def test_003_CreateTransects(self):
        right=create_transects(self.mar_shoreline,
                           sampling_step=150,
                           tick_length=50,
                           location='mar' ,crs=crs_dict_string['mar'],
                           side='right'
                          )
        left=create_transects(self.mar_shoreline,
                                   sampling_step=150,
                                   tick_length=50,
                                   location='mar' ,crs=crs_dict_string['mar'],
                                   side='left'
                                  )
        self.assertTrue(right.touches(left).all())

class TestSandpyper(unittest.TestCase):
    """Tests the extraction from profiles function."""

    @classmethod
    def setUpClass(cls):
        ############################# Profile extraction module ######################

        cls.gdf = extract_from_folder(dataset_folder=dsms_dir_path,
                        transect_folder=transects_path,
                        mode="dsm",sampling_step=1,
                        list_loc_codes=loc_codes,
                        add_xy=True)

        cls.gdf_rgb = extract_from_folder(dataset_folder=orthos_dir_path,
                        transect_folder=transects_path,
                        mode="ortho",sampling_step=1,
                        list_loc_codes=loc_codes,
                        add_xy=True)


        ############################# Silhouette Analysis and KMeans clustering module ######################


        cls.rgbz_gdf = pd.merge(cls.gdf,cls.gdf_rgb[["band1","band2","band3","point_id"]],on="point_id",validate="one_to_one")
        cls.rgbz_gdf['geometry']=cls.rgbz_gdf.coordinates

        # replace empty values with np.NaN
        cls.rgbz_gdf = cls.rgbz_gdf.replace("", np.NaN)

        # and convert the z column into floats.
        cls.rgbz_gdf['z'] = cls.rgbz_gdf.z.astype("float")

        # Our rasters have NaN values set to -32767.0. Thus, we replace them with np.Nan.
        cls.rgbz_gdf.z.replace(-32767.0,np.nan,inplace=True)

        # Our rasters have NaN values set to -32767.0. Thus, we replace them with np.Nan.
        feature_set=["band1","band2","band3","distance"]
        cls.sil_df = get_sil_location(cls.rgbz_gdf,
                                ks=(2,15),
                                feature_set=feature_set,
                               random_state=10)

        cls.opt_k = get_opt_k(cls.sil_df, sigma=0 )
        cls.data_classified = kmeans_sa(cls.rgbz_gdf, cls.opt_k, feature_set=feature_set)


        cls.dh_df=compute_multitemporal(cls.data_classified,
                              date_field='raw_date', filter_sand=False,
                              sand_label_field='label_sand')

        cls.dt_details = create_details_df(cls.dh_df, loc_full)


        ############################# HotSpot module ######################

        cls.lisa_df_dist=LISA_site_level(dh_df=cls.dh_df,
                                mode='distance',
                                distance_value=35,
                                geometry_column="geometry",
                                crs_dict_string=crs_dict_string)

        cls.lisa_df_knn=LISA_site_level(dh_df=cls.dh_df,
                                mode='knn',k_value=50,
                                distance_value=0,
                                geometry_column="geometry",
                                crs_dict_string=crs_dict_string)

        cls.lisa_df_idw=LISA_site_level(dh_df=cls.dh_df,
                        mode='idw',k_value=0,
                        distance_value=35,
                        geometry_column="geometry",
                        crs_dict_string=crs_dict_string)


        ############################# Dynamics module ######################


        cls.D = Discretiser(bins=5, method="JenksCaspall", labels=labels)


    @classmethod
    def tearDownClass(cls):
        cls.gdf
        cls.gdf_rgb
        cls.rgbz_gdf
        cls.sil_df
        cls.opt_k
        cls.data_classified
        cls.dh_df
        cls.dt_details
        cls.lisa_df_dist
        cls.lisa_df_knn
        cls.lisa_df_idw

    def test_004_extract_DSM(self):
        """Test extraction from folders of DSMs."""

        nan_values=-10000 # the values representing NaN in the test rasters
        nan_out = np.count_nonzero(np.isnan(np.array(self.gdf.z).astype("f"))) # count the number of points outside the raster extents
        nan_raster = np.count_nonzero(self.gdf.z == nan_values) # count the number of points in NoData areas within the raster extents.Should be zero.

        # check sampling step of points on first, last and random transects
        test_slice=self.gdf.query("location=='mar' & survey_date=='2019-05-16'").copy()
        test_slice.loc[:,'next_point']=test_slice.loc[:,'coordinates'].shift(1)
        test_slice_tr0=test_slice.query("tr_id==0").iloc[1:,:].copy()
        test_slice_last=test_slice.query(f"tr_id=={max(test_slice.tr_id.unique())}").copy()
        test_slice_rand=test_slice.query(f"tr_id=={np.random.randint(min(test_slice.tr_id.unique()),max(test_slice.tr_id.unique()))}").iloc[1:,:].copy()

        pts_spacing_0=np.nanmean(test_slice_tr0.coordinates.set_crs(32754).distance(test_slice_tr0.next_point.set_crs(32754)))
        pts_spacing_last=np.nanmean(test_slice_last.coordinates.set_crs(32754).distance(test_slice_last.next_point.set_crs(32754)))
        pts_spacing_rand=np.nanmean(test_slice_rand.coordinates.set_crs(32754).distance(test_slice_rand.next_point.set_crs(32754)))


        self.assertEqual(self.gdf.shape, (32805, 10))
        self.assertEqual(nan_out, 9316) # differs from the printed out value from the function extract_from_folder as includes additional cleaning.
        self.assertEqual(nan_raster, 0)
        self.assertEqual(self.gdf.z.sum(), 55398.192078785054)
        self.assertIsInstance(self.gdf,  gpd.GeoDataFrame)
        self.assertAlmostEqual(pts_spacing_0, 1) # check if the sampling point spacing is actually 1m, as specified in the fn parameter
        self.assertAlmostEqual(pts_spacing_last, 1) # check if the sampling point spacing is actually 1m, as specified in the fn parameter
        self.assertAlmostEqual(pts_spacing_rand, 1) # check if the sampling point spacing is actually 1m, as specified in the fn parameter


    def test_005_extract_ORTHO(self):
        """Test extraction from folders of orthophotos"""


        nan_values=-10000 # the values representing NaN in the test rasters
        nan_out = np.count_nonzero(
            np.isnan(np.array(self.gdf_rgb[["band1", "band2", "band3"]]).astype("f")) # count the number of points outside the raster extents
        )
        nan_raster = np.count_nonzero(self.gdf_rgb.band1 == nan_values) # count the number of points in NoData areas within the raster extents

        # check sampling step of points on first, last and random transects.
        test_slice=self.gdf_rgb.query("location=='mar' & survey_date=='2019-05-16'").copy()
        test_slice.loc[:,'next_point']=test_slice.loc[:,'coordinates'].shift(1)
        test_slice_tr0=test_slice.query("tr_id==0").iloc[1:,:].copy()
        test_slice_last=test_slice.query(f"tr_id=={max(test_slice.tr_id.unique())}").copy()
        test_slice_rand=test_slice.query(f"tr_id=={np.random.randint(min(test_slice.tr_id.unique()),max(test_slice.tr_id.unique()))}").iloc[1:,:].copy()

        pts_spacing_0=np.nanmean(test_slice_tr0.coordinates.distance(test_slice_tr0.next_point.set_crs(test_slice.crs)))
        pts_spacing_last=np.nanmean(test_slice_last.coordinates.distance(test_slice_last.next_point.set_crs(test_slice_last.crs)))
        pts_spacing_rand=np.nanmean(test_slice_rand.coordinates.distance(test_slice_rand.next_point.set_crs(test_slice_rand.crs)))


        self.assertEqual(self.gdf_rgb.shape, (32805, 11))
        self.assertEqual(nan_out, 27954)
        self.assertEqual(nan_raster, 0)
        self.assertEqual(self.gdf_rgb.band1.sum(), 3178389.0) # check if the values are returned as expected by evaluating their summed value
        self.assertEqual(self.gdf_rgb.band2.sum(), 3189458.0)
        self.assertEqual(self.gdf_rgb.band3.sum(), 2920800.0)
        self.assertIsInstance(self.gdf_rgb,  gpd.GeoDataFrame)
        self.assertAlmostEqual(pts_spacing_0, 1) # check if the sampling point spacing is actually 1m, as specified in the fn parameter
        self.assertAlmostEqual(pts_spacing_last, 1) # check if the sampling point spacing is actually 1m, as specified in the fn parameter
        self.assertAlmostEqual(pts_spacing_rand, 1) # check if the sampling point spacing is actually 1m, as specified in the fn parameter


    def test_006_point_IDs(self):
        """Test extracted point IDs are the same"""
        self.assertTrue((self.gdf_rgb.point_id==self.gdf.point_id).all())

    def test_007_Dynamics_Class(self):
        self.D.fit(self.lisa_df_dist, absolute=True, print_summary=True)
        self.D.infer_weights()
        self.D.BCD_compute_location("geometry","all",True)
        self.D.plot_trans_matrices(relabel_dict)
        self.D.plot_location_ebcds()

if __name__ == '__main__':
    unittest.main()
