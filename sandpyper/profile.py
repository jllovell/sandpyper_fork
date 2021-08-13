"""Profile module."""

from rasterio.windows import Window
from rasterio.transform import rowcol
import rasterio as ras
import numpy as np
import richdem as rd
from shapely.geometry import Point
import pandas as pd
import geopandas as gpd
from tqdm.notebook import tqdm
import datetime

import os
import time
import warnings
import pickle


from sandpyper.dynamics import compute_multitemporal
from sandpyper.hotspot import LISA_site_level
from sandpyper.labels import kmeans_sa, cleanit



from sandpyper.outils import (cross_ref,create_spatial_id,
    create_id,
    filter_filename_list,
    getListOfFiles,
    getDate,
    getLoc,
    check_dicts_duplicated_values
)



class ProfileSet():
    """This class sets up the monitoring global parameters, input files directories and creates a check dataframe to confirm all CRSs and files are matched up correctly.

    Args:
        dirNameDSM (str): Path of the directory containing the DSM datasets.
        dirNameOrtho (str): Path of the directory containing the orthophotos datasets.
        dirNameTrans (str): Path of the directory containing the transect files (.gpkg, .shp).
        transects_spacing (float): The alonghsore spacing between transects.
        loc_codes (list): List of strings of location codes.
        loc_search_dict (dict): A dictionary where keys are the location codes and values are lists containing the expected full location string, including the location code itself (["wbl","Warrnambool", "warrnambool","warrny"]).
        crs_dict_string (dict): Dictionary storing location codes as key and crs information as values, in dictionary form.
        check (str, optional): If 'all', the check dataframe will contain both DSMs and orthophotos information. If one of 'dsm' or 'ortho', only check the desired data type.

    Returns:
        object: ProfileSet object.
    """
    def __init__(self,
                 dirNameDSM,
                 dirNameOrtho,
                 dirNameTrans,
                 transects_spacing,
                 loc_codes,
                 loc_search_dict,
                 crs_dict_string,
                check='all'):


        self.dirNameDSM=dirNameDSM
        self.dirNameOrtho=dirNameOrtho
        self.dirNameTrans=dirNameTrans
        self.transects_spacing=transects_spacing

        self.loc_codes=loc_codes
        self.=loc_search_dict
        self.crs_dict_string=crs_dict_string

        if check=="dsm":
            path_in=self.dirNameDSM
        elif check == "ortho":
            path_in=self.dirNameOrtho
        elif check == "all":
            path_in=[self.dirNameDSM, self.dirNameOrtho]


        self.check=cross_ref(path_in,
                        self.dirNameTrans,
                        print_info=True,
                        loc_search_dict=self.loc_search_dict,
                        list_loc_codes=self.loc_codes)

    def save(self, name, out_dir):
        """Save object using pickle.

        Args:
            name (str): Name of the file to save.
            out_dir (str): Path to the directory where to save the object.

        Returns:
            pickle file.
        """

        savetxt=f"{os.path.join(out_dir,name)}.p"
        pickle.dump( self, open( savetxt, "wb" ) )
        print(f"ProfileSet object saved in {savetxt} .")

    def extract_profiles(self,
                         mode,
                         tr_ids,
                         sampling_step,
                         lod_mode,
                         add_xy,
                         add_slope=False,
                         default_nan_values=-10000):
        """Extract pixel values from orthophotos, DSMs or both, along transects in all surveys as a GeoDataFrame stored in the ProfileSet.profiles attribute.

        Args:
            mode (str): If 'dsm', extract from DSMs. If 'ortho', extracts from orthophotos. if "all", extract from both.
            tr_ids (str): The name of the field in the transect file that is used to store the transects ID.
            sampling_step (float): Distance along-transect to extract data points from. In meters.
            add_xy (bool): If True, adds extra columns with long and lat coordinates in the input CRS.
            add_slope (bool): If True, computes slope raster in degrees (increased procesing time)
            and extract slope values across transects.
            default_nan_values (int): Value used for NoData specification in the rasters used.
            In Pix4D, this is -10000 (default).

         Returns:
            attribute: .profiles dataframe
        """

        if mode=="dsm":
            path_in=self.dirNameDSM
        elif mode == "ortho":
            path_in=self.dirNameOrtho
        elif mode == "all":
            path_in=[self.dirNameDSM,self.dirNameOrtho]
        else:
            raise NameError("mode must be either 'dsm','ortho' or 'all'.")

        if mode in ["dsm","ortho"]:

            profiles=extract_from_folder(dataset_folder=path_in,
                transect_folder=self.dirNameTrans,
                tr_ids=tr_ids,
                mode=mode,sampling_step=sampling_step,
                list_loc_codes=self.loc_codes,
                add_xy=add_xy,
                add_slope=add_slope,
                default_nan_values=default_nan_values)

            profiles["distance"]=np.round(profiles.loc[:,"distance"].values.astype("float"),2)

        elif mode == "all":

            print("Extracting elevation from DSMs . . .")
            profiles_z=extract_from_folder( dataset_folder=path_in[0],
                    transect_folder=self.dirNameTrans,
                    mode="dsm",
                    tr_ids=tr_ids,
                    sampling_step=sampling_step,
                    list_loc_codes=self.loc_codes,
                    add_xy=add_xy,
                    add_slope=add_slope,
                    default_nan_values=default_nan_values )

            print("Extracting rgb values from orthos . . .")
            profiles_rgb=extract_from_folder(dataset_folder=path_in[1],
                transect_folder=self.dirNameTrans,
                tr_ids=tr_ids,
                mode="ortho",sampling_step=sampling_step,
                list_loc_codes=self.loc_codes,
                add_xy=add_xy,
                default_nan_values=default_nan_values)

            profiles_rgb["distance"]=np.round(profiles_rgb.loc[:,"distance"].values.astype("float"),2)
            profiles_z["distance"]=np.round(profiles_z.loc[:,"distance"].values.astype("float"),2)

            profiles_merged = pd.merge(profiles_z,profiles_rgb[["band1","band2","band3","point_id"]],on="point_id",validate="one_to_one")
            profiles_merged=profiles_merged.replace("", np.NaN)
            profiles_merged['z']=profiles_merged.z.astype("float")

            self.profiles=profiles_merged

        else:
            raise NameError("mode must be either 'dsm','ortho' or 'all'.")

        self.sampling_step=sampling_step


        if os.path.isdir(lod_mode):
            if mode == 'dsm':
                lod_path_data=self.dirNameDSM
            elif mode == 'all':
                lod_path_data=path_in[0]

            print("Extracting LoD values")

            lod=extract_from_folder( dataset_folder=lod_path_data,
                    transect_folder=lod_mode,
                    tr_ids=tr_ids,
                    mode="dsm",
                    sampling_step=sampling_step,
                    list_loc_codes=self.loc_codes,
                    add_xy=False,
                    add_slope=False,
                    default_nan_values=default_nan_values )
            self.lod=lod


        elif isinstance(lod_mode, (float, int)) or lod_mode==None:
            self.lod=lod

        else:
            raise ValueError("lod_mode must be a path directing to the folder of lod profiles, a numerical value or None.")



    def kmeans_sa(self, ks, feature_set, thresh_k=5, random_state=10 ):
        """Cluster data using a specified feature set with KMeans algorithm and a dictionary of optimal numebr of clusters to use for each survey (see get_sil_location and get_opt_k functions).

        Args:
            ks (dictionary): Number of clusters (k) or dictionary containing a k for each survey.
            feature_set (list): List of names of features (columns of the ProfileSet.profiles dataframe) to use for clustering.
            thresh_k (int, optional): Minimim k to be used. If survey-specific optimal k is below this value, then k equals the average k of all above threshold values.
            random_state (int, optional): Random seed used to make the randomisation deterministic.

         Returns:
            label_k: new column in ProfileSet.profiles dataframe storing each point cluster label.
        """

        labels_df=kmeans_sa(merged_df=self.profiles,
            ks=ks,
            feature_set=feature_set,
            thresh_k=thresh_k,
            random_state=random_state)

        self.profiles =  self.profiles.merge(labels_df[["point_id","label_k"]], how="right", on="point_id", validate="one_to_one")


    def cleanit(self, l_dicts, cluster_field='label_k', fill_class='sand',
                watermasks_path=None, water_label='water',
                shoremasks_path=None, label_corrections_path=None,
                default_crs={'init': 'epsg:32754'}, crs_dict_string=None,
               geometry_field='coordinates'):
        """Transforms labels k into meaningful classes (sand, water, vegetation ,..) and apply fine-tuning correction, shoremasking and watermasking cleaning procedures.

        Args:
            l_dicts (list): List of classes dictionaries containing the interpretations of each label k in every survey.
            cluster_field (str): Name of the field storing the labels k to transform (default "label_k").
            fill_class (str): Class assigned to points that have no label_k specified in l_dicts.
            watermasks_path (str): Path to the watermasking file.
            water_label: .
            shoremasks_path: Path to the shoremasking file.
            label_corrections_path: Path to the label correction file.
            default_crs: CRS used to digitise correction polygons.
            crs_dict_string: Dictionary storing location codes as key and crs information as values, in dictionary form.
            geometry_field: Field that stores the point geometry (default 'geometry').

         Returns:
            label_k: new column in ProfileSet.profiles dataframe storing each point cluster label.
        """


        processes=[]
        if label_corrections_path: processes.append("polygon finetuning")
        if watermasks_path: processes.append("watermasking")
        if shoremasks_path: processes.append("shoremasking")
        if len(processes)==0: processes.append('none')

        self.cleaning_steps = processes

        self.profiles = cleanit(to_clean=self.profiles,l_dicts=l_dicts, cluster_field=cluster_field, fill_class=fill_class,
                    watermasks_path=watermasks_path, water_label=water_label,
                    shoremasks_path=shoremasks_path, label_corrections_path=label_corrections_path,
                    default_crs=default_crs, crs_dict_string=self.crs_dict_string,
                   geometry_field=geometry_field)




##____________ FUNCTIONS____________________________________________________

def get_terrain_info(x_coord, y_coord, rdarray):
    """
    Returns the value of the rdarray rasters.

    Args:
        x_coord, y_coord (float): Projected coordinates of pixel to extract value.
        rdarray (rdarray): rdarray dataset.

    Returns:
        rdarray pixel value.
    """

    geotransform = rdarray.geotransform

    xOrigin = geotransform[0]  # top-left X
    yOrigin = geotransform[3]  # top-left y
    pixelWidth = geotransform[1]  # horizontal pixel resolution
    pixelHeight = geotransform[5]  # vertical pixel resolution
    px = int((x_coord - xOrigin) / pixelWidth)  # transform geographic to image coords
    py = int((y_coord - yOrigin) / pixelHeight)  # transform geographic to image coords

    try:
        return rdarray[py, px]
    except BaseException:
        return np.nan


def get_elevation(x_coord, y_coord, raster, bands, transform):
    """
    Returns the value of the raster at a specified location and band.

    Args:
        x_coord, y_coord (float): Projected coordinates of pixel to extract value.
        raster (rasterio open file): Open raster object, from rasterio.open(raster_filepath).
        bands (int): number of bands.
        transform (Shapely Affine obj): Geotransform of the raster.
    Returns:
        raster pixel value.
    """
    elevation = []
    row, col = rowcol(transform, x_coord, y_coord, round)

    for j in np.arange(bands):  # we could iterate thru multiple bands

        try:
            data_z = raster.read(1, window=Window(col, row, 1, 1))
            elevation.append(data_z[0][0])
        except BaseException:
            elevation.append(np.nan)

    return elevation


def get_raster_px(x_coord, y_coord, raster, bands=None, transform=None):

    if isinstance(raster, richdem.rdarray):
        transform = rdarray.geotransform

        xOrigin = transform[0]  # top-left X
        yOrigin = transform[3]  # top-left y
        pixelWidth = transform[1]  # horizontal pixel resolution
        pixelHeight = transform[5]  # vertical pixel resolution
        px = int(
            (x_coord - xOrigin) / pixelWidth
        )  # transform geographic to image coords
        py = int(
            (y_coord - yOrigin) / pixelHeight
        )  # transform geographic to image coords

        try:
            return rdarray[py, px]
        except BaseException:
            return np.nan

    else:
        if bands == None:
            bands = raster.count()

        if bands == 1:
            try:
                px_data = raster.read(1, window=Window(col, row, 1, 1))
                return px_data[0][0]
            except BaseException:
                return np.nan
        elif bands > 1:
            px_data = []
            for band in range(1, bands + 1):
                try:
                    px_data_band = raster.read(band, window=Window(col, row, 1, 1))
                    px_data.append(px_data_band[0][0])
                except BaseException:
                    px_data.append(np.nan)

            return px_data


def get_profiles(
    dsm,
    transect_file,
    tr_ids,
    transect_index,
    step,
    location,
    date_string,
    add_xy=False,
    add_terrain=False,
):
    """
    Returns a tidy GeoDataFrame of profile data, extracting raster information
    at a user-defined (step) meters gap along each transect.

    Args:
    dsm (str): path to the DSM raster.
    transect_file (str): path to the transect file.
    transect_index (int): index of the transect to extract information from.
    step (int,float): sampling distance from one point to another in meters along the transect.
    location (str): location code
    date_string: raw format of the survey date (20180329)
    add_xy (bool): True to add X and Y coordinates fields.
    add_terrain (bool): True to add slope in degrees. Default to False.

    Returns:
    gdf (GeoDataFrame) : Profile data extracted from the raster.
    """

    ds = ras.open(dsm, "r")
    bands = ds.count  # get raster bands. One, in a classic DEM
    transform = ds.transform  # get geotransform info

    # index each transect and store it a "line" object
    line = transect_file.loc[transect_index]

    if tr_ids=='reset':
        line_id=line.name
    elif isinstance(tr_ids,str) and tr_ids in line.index:
        line_id=line.loc[tr_ids]
    else:
        raise ValueError(f"'tr_ids' must be either 'reset' or the name of an existing column o the transect files. '{tr_ids}' was passed.")


    length_m = line.geometry.length

    # Creating empty lists of coordinates, elevations and distance (from start
    # to end points along each transect lines)

    x = []
    y = []
    z = []
    slopes = []

    # The "distance" object is and empty list which will contain the x variable
    # which is the displacement from the shoreward end of the transects toward
    # the foredunes.

    distance = []

    for currentdistance in np.arange(0, int(length_m), step):

        # creation of the point on the line
        point = line.geometry.interpolate(currentdistance)
        xp, yp = (
            point.x,
            point.y,
        )  # storing point xy coordinates into xp,xy objects, respectively
        x.append(xp)  # see below
        y.append(
            yp
        )  # append point coordinates to previously created and empty x,y lists
        # extraction of the elevation value from DSM
        z.append(get_elevation(xp, yp, ds, bands, transform)[0])
        if str(type(add_terrain)) == "<class 'richdem.rdarray'>":
            slopes.append(get_terrain_info(xp, yp, add_terrain))
        else:
            pass

        # append the distance value (currentdistance) to distance list
        distance.append(currentdistance)

    # Below, the empty lists tr_id_list and the date_list will be filled by strings
    # containing the transect_id of every point as stored in the original dataset
    # and a label with the date as set in the data setting section, after the input.

    zs= pd.Series((elev for elev in z))

    if str(type(add_terrain)) == "<class 'richdem.rdarray'>":
        slopes_series= pd.Series((slope for slope in slope))
        df = pd.DataFrame({"distance": distance, "z": zs, "slope":slopes_series})
    else:
        df = pd.DataFrame({"distance": distance, "z": zs})


    df["coordinates"] = list(zip(x, y))
    df["coordinates"] = df["coordinates"].apply(Point)
    df["location"] = location
    df["survey_date"] = pd.to_datetime(date_string, yearfirst=True, dayfirst=False, format="%Y%m%d")
    df["raw_date"] = date_string
    df["tr_id"] = int(line_id)
    gdf = gpd.GeoDataFrame(df, geometry="coordinates")


    # The proj4 info (coordinate reference system) is gathered with
    # Geopandas and applied to the newly created one.
    gdf.crs = str(transect_file.crs)

    # Transforming non-hashable Shapely coordinates to hashable strings and
    # store them into a variable

    # Let's create unique IDs from the coordinates values, so that the Ids
    # follows the coordinates
    gdf["point_id"] = [create_id(gdf.iloc[i]) for i in range(0, gdf.shape[0])]

    if bool(add_xy):
        # Adding long/lat fields
        gdf["x"] = gdf.coordinates.x
        gdf["y"] = gdf.coordinates.y
    else:
        pass

    return gdf


def get_dn(x_coord, y_coord, raster, bands, transform):
    """
    Returns the value of the raster at a specified location and band.

    Args:
        x_coord, y_coord (float): Projected coordinates of pixel to extract value.
        raster (rasterio open file): Open raster object, from rasterio.open(raster_filepath).
        bands (int): number of bands.
        transform (Shapely Affine obj): Geotransform of the raster.
    Returns:
        raster pixel value.
    """
    # Let's create an empty list where we will store the elevation (z) from points
    # With GDAL, we extract 4 components of the geotransform (gt) of our north-up image.

    dn_val = []
    row, col = rowcol(transform, x_coord, y_coord, round)

    for j in range(1, 4):  # we could iterate thru multiple bands

        try:
            data = raster.read(j, window=Window(col, row, 1, 1))
            dn_val.append(data[0][0])
        except BaseException:
            dn_val.append(np.nan)
    return dn_val


def get_profile_dn(
    ortho, transect_file,
    transect_index, tr_ids,
    step, location, date_string, add_xy=False
):
    """
    Returns a tidy GeoDataFrame of profile data, extracting raster information
    at a user-defined (step) meters gap along each transect.

    Args:
    ortho (str): path to the DSM raster.
    transect_file (str): path to the transect file.
    transect_index (int): index of the transect to extract information from.
    step (int,float): sampling distance from one point to another in meters along the transect.
    location (str): location code
    date_string: raw format of the survey date (20180329)
    add_xy (bool): True to add X and Y coordinates fields.

    Returns:
    gdf (GeoDataFrame) : Profile data extracted from the raster.
    """

    ds = ras.open(ortho, "r")

    bands = ds.count

    transform = ds.transform

    line = transect_file.loc[transect_index]

    if tr_ids=='reset':
        line_id=line.name
    elif isinstance(tr_ids,str) and tr_ids in line.index:
        line_id=line.loc[tr_ids]
    else:
        raise ValueError(f"'tr_ids' must be either 'reset' or the name of an existing column o the transect files. '{tr_ids}' was passed.")


    length_m = line.geometry.length

    x = []
    y = []
    dn = []
    distance = []
    for currentdistance in np.arange(0, int(length_m), step):
        # creation of the point on the line
        point = line.geometry.interpolate(currentdistance)
        xp, yp = (
            point.x,
            point.y,
        )  # storing point xy coordinates into xp,xy objects, respectively
        x.append(xp)  # see below
        y.append(
            yp
        )  # append point coordinates to previously created and empty x,y lists
        dn.append(get_dn(xp, yp, ds, bands, transform))

        distance.append(currentdistance)

    dn1 = pd.Series((v[0] for v in dn))
    dn2 = pd.Series((v[1] for v in dn))
    dn3 = pd.Series((v[2] for v in dn))
    df = pd.DataFrame({"distance": distance, "band1": dn1, "band2": dn2, "band3": dn3})
    df["coordinates"] = list(zip(x, y))
    df["coordinates"] = df["coordinates"].apply(Point)
    df["location"] = location
    df["survey_date"] = pd.to_datetime(date_string, yearfirst=True, dayfirst=False, format="%Y%m%d")
    df["raw_date"] = date_string
    df["tr_id"] = int(line_id)
    gdf_rgb = gpd.GeoDataFrame(df, geometry="coordinates")

    # Last touch, the proj4 info (coordinate reference system) is gathered with
    # Geopandas and applied to the newly created one.
    gdf_rgb.crs = str(transect_file.crs)

    # Let's create unique IDs from the coordinates values, so that the Ids
    # follows the coordinates
    gdf_rgb["point_id"] = [
        create_id(gdf_rgb.iloc[i]) for i in range(0, gdf_rgb.shape[0])
    ]

    if bool(add_xy):
        # Adding long/lat fields
        gdf_rgb["x"] = gdf_rgb.coordinates.x
        gdf_rgb["y"] = gdf_rgb.coordinates.y
    else:
        pass

    return gdf_rgb


def extract_from_folder(
    dataset_folder,
    transect_folder,
    tr_ids,
    list_loc_codes,
    mode,
    sampling_step,
    add_xy=False,
    add_slope=False,
    default_nan_values=-10000
):
    """
    Wrapper to extract profiles from all rasters inside a folder.

    Warning: The folders must contain the geotiffs and geopackages only.

    Args:
        dataset_folder (str): Path of the directory containing the datasets (geotiffs, .tiff).
        transect_folder (str): Path of the directory containing the transects (geopackages, .gpkg).
        tr_ids (str): If 'reset', a new incremental transect_id will be automatically assigned.\
        If the name of a column in the transect files is provided, use that column as transect IDs.
        list_loc_codes (list): list of strings containing location codes.
        mode (str): If 'dsm', extract from DSMs. If 'ortho', extracts from orthophotos.
        sampling_step (float): Distance along-transect to sample points at. In meters.
        add_xy (bool): If True, adds extra columns with long and lat coordinates in the input CRS.
        add_slope (bool): If True, computes slope raster in degrees (increased procesing time)
        and extract slope values across transects.
        nan_values (int): Value used for NoData in the raster format.
        In Pix4D, this is -10000 (Default).

    Returns:
        A geodataframe with survey and topographical or color information extracted.
    """

    # Get a list of all the filenames and path
    list_files = filter_filename_list(
        getListOfFiles(dataset_folder), fmt=[".tif", ".tiff"]
    )

    dates = [getDate(dsm_in) for dsm_in in list_files]

    # List all the transects datasets
    if os.path.isdir(transect_folder):
        list_trans = getListOfFiles(transect_folder)
    elif os.path.isfile(transect_folder):
        list_trans = getListOfFiles(transect_folder)

    start = time.time()

    # Set the sampling distance (step) for your profiles

    gdf = pd.DataFrame()
    counter = 0

    if bool(add_slope):
        warnings.warn(
            "WARNING: add_terrain could increas processing time considerably for fine scale DSMs."
        )

    for dsm in tqdm(list_files):
        with ras.open(dsm, 'r') as ds:
            nan_values = ds.nodata
            if nan_values:
                pass
            else:
                nan_values=default_nan_values

        date_string = getDate(dsm)
        location = getLoc(dsm, list_loc_codes)


        if bool(add_slope):

            terr = rd.LoadGDAL(dsm, no_data=nan_values)
            print(
                f"Computing slope DSM in degrees in {location} at date: {date_string} . . ."
            )
            slope = rd.TerrainAttribute(terr, attrib="slope_degrees")
        else:
            slope = False

        transect_file_input = [a for a in list_trans if location in a]
        transect_file = gpd.read_file(transect_file_input[0])

        tr_list = np.arange(0, transect_file.shape[0])
        for i in tqdm(tr_list):
            if mode == "dsm":
                temp = get_profiles(
                    dsm=dsm,
                    transect_file=transect_file,
                    tr_ids=tr_ids,
                    transect_index=i,
                    step=sampling_step,
                    location=location,
                    date_string=date_string,
                    add_xy=add_xy,
                    add_terrain=slope,
                )
            elif mode == "ortho":
                temp = get_profile_dn(
                    ortho=dsm,
                    transect_file=transect_file,
                    transect_index=i,
                    step=sampling_step,
                    location=location,
                    tr_ids=tr_ids,
                    date_string=date_string,
                    add_xy=add_xy,
                )

            gdf = pd.concat([temp, gdf], ignore_index=True)

        counter += 1

    if counter == len(list_files):
        print("Extraction succesfull")
    else:
        print(f"There is something wrong with this dataset: {list_files[counter]}")

    end = time.time()
    timepassed = end - start

    print(
        f"Number of points extracted:{gdf.shape[0]}\nTime for processing={timepassed} seconds\nFirst 10 rows are printed below"
    )

    if mode == "dsm":
        nan_out = np.count_nonzero(np.isnan(np.array(gdf.z).astype("f")))
        nan_raster = np.count_nonzero(gdf.z == nan_values)
        gdf.z.replace(-10000, np.nan, inplace=True)

    elif mode == "ortho":
        nan_out = np.count_nonzero(
            np.isnan(np.array(gdf[["band1", "band2", "band3"]]).astype("f"))
        )
        nan_raster = np.count_nonzero(gdf.band1 == nan_values)
        gdf.band1.replace(0.0, np.nan, inplace=True)
        gdf.band2.replace(0.0, np.nan, inplace=True)
        gdf.band3.replace(0.0, np.nan, inplace=True)

    print(
        f"Number of points outside the raster extents: {nan_out}\nThe extraction assigns NaN."
    )
    print(
        f"Number of points in NoData areas within the raster extents: {nan_raster}\nThe extraction assigns NaN."
    )

    return gdf
