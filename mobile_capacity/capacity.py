from mobile_capacity.spatial import meters_to_degrees_latitude, create_voronoi_cells
from mobile_capacity.utils import initialize_logger, log_progress_bar
from mobile_capacity.handlers.populationdatahandler import PopulationDataHandler
from mobile_capacity.handlers.srtmdatahandler import SRTMDataHandler
from mobile_capacity.entities.pointofinterest import PointOfInterestCollection
from mobile_capacity.entities.cellsite import CellSiteCollection
from mobile_capacity.entities.visibilitypair import VisibilityPairCollection
from mobile_capacity.visibility import Visibility
import numpy as np
import pandas as pd
import geopandas as gpd
import os

class Capacity:
    """
    A class for analyzing and calculating mobile network capacity in a given area.

    This class provides methods to analyze cell site coverage, population distribution,
    and network capacity based on various parameters such as bandwidth, spectrum allocation,
    and user data consumption.

    Attributes:
        country_code (str): ISO3 country code for the area of analysis.
        bw_L850 (float): Bandwidth in MHz for L700 to L900 spectrum.
        bw_L1800 (float): Bandwidth in MHz for L1800 to L2100 spectrum.
        bw_L2600 (float): Bandwidth in MHz for L2300 to L2600 spectrum.
        cco (float): Control channel overhead in percentage.
        sectors_per_site (int): Number of sectors per cell site.
        angles_num (int): Number of angles for analysis.
        rotation_angle (float): Rotation angle in degrees.
        dlthtarg (float): Download throughput target in Mbps.
        mbb_subscr (float): Active mobile-broadband subscriptions per 100 people.
        oppopshare (float): Percentage of population using operator services.
        nonbhu (float): Connection usage in non-busy hour in percentage.
        nbhours (int): Number of non-busy hours per day.
        rb_num_multiplier (int): Resource block number multiplier.
        max_radius (int): Maximum buffer radius for analysis.
        min_radius (int): Minimum buffer radius for analysis.
        radius_step (int): Step size for buffer radius increments.
        cellsite_search_radius (int): Cell site search radius in meters.
        poi_antenna_height (int): Point of interest antenna height in meters.
        dataset_year (int): Year of the dataset being used.
        one_km_res (bool): Flag for using 1km resolution data.
        un_adjusted (bool): Flag for using UN-adjusted data.
        enable_logging (bool): Flag to enable logging.
        use_secure_files (bool): Flag to use secure files for bandwidth data.

    Methods:
        _get_population_data(): Loads and returns population data.
        get_dl_bitrate(poi_distances): Calculates downlink bitrate based on distances.
        poiddatareq(d): Calculates required resource blocks for target throughput.
        brrbpopcd(popcd): Calculates bitrate per resource block at population center.
        avubrnonbh(udatavmonth): Calculates average user bitrate in non-busy hour.
        upopbr(avubrnonbh, pop): Calculates user population bitrate.
        upoprbu(upopbr, brrbpopcd): Calculates user population resource block utilization.
        cellavcap(avrbpdsch, upoprbu): Calculates available cell capacity.
        sufcapch(cellavcap, rbdlthtarg): Checks if capacity is sufficient.
        capacity_checker(d, popcd, udatavmonth, pop): Performs overall capacity check.
        calculate_buffer_areas(): Calculates buffer areas around cell sites.
        mbbtps(): Calculates mobile broadband traffic per subscription.

    The class uses various data sources including population data, cell site locations,
    and terrain information to perform comprehensive network capacity analysis.
    """
    def __init__(self,
                 country_code: str,
                 data_dir: str,
                 logs_dir: str,
                 poi: PointOfInterestCollection,
                 cellsites: CellSiteCollection,
                 bw_L850, bw_L1800, bw_L2600,
                 cco, max_radius, min_radius, radius_step, angles_num, rotation_angle, dlthtarg, nonbhu, mbb_subscr,
                 use_secure_files: bool = False,
                 sectors_per_site: int = 3,
                 cellsite_search_radius: int = 35000,
                 poi_antenna_height: int = 15,
                 rb_num_multiplier: int = 5,
                 visibility: VisibilityPairCollection = None,
                 area: gpd.GeoDataFrame = None,
                 dataset_year: int = 2020,
                 one_km_res: bool = True,
                 un_adjusted: bool = True,
                 nbhours: int = 10,
                 oppopshare: int = 50,
                 enable_logging: bool = False):

        # Parameters
        self.country_code = country_code  # Country ISO3 code
        self.bw_L850 = bw_L850  # MHz on L700 to L900 spectrum bandwidth
        self.bw_L1800 = bw_L1800  # MHz on L1800 to L2100 spectrum bandwidth
        self.bw_L2600 = bw_L2600  # MHz on L2300 to L2600 spectrum bandwidth
        self.cco = cco  # Control channel overhead in %
        self.sectors_per_site = sectors_per_site  # Number of sectors per site
        self.angles_num = angles_num  # Number of angles
        self.rotation_angle = rotation_angle  # Rotation angle in degrees
        self.dlthtarg = dlthtarg  # Download throughput target in Mbps
        self.mbb_subscr = mbb_subscr  # Active mobile-broadband subscriptions per 100 people
        self.oppopshare = oppopshare  # Percentage of population using operator services in %
        self.nonbhu = nonbhu  # Connection usage in non-busy hour in %
        self.nbhours = nbhours  # Number of non-busy hours per day
        self.rb_num_multiplier = rb_num_multiplier  # Resource block number multiplier
        self.max_radius = max_radius  # Maximum buffer radius
        self.min_radius = min_radius  # Maximum buffer radius
        self.radius_step = radius_step  # Maximum buffer radius

        # Visibility analysis parameters
        self.cellsite_search_radius = cellsite_search_radius  # Cell site search radius in meters
        self.poi_antenna_height = poi_antenna_height  # Point of interest antenna height in meters

        # Constants
        self.days = 30.4  # Days in one month
        self.minperhour = 60  # Number of minutes per hour
        self.secpermin = 60  # Number of seconds per minute
        self.bitsingbit = 1000000000  # Bits in one gigabit
        self.bitsinkbit = 1000  # Bits in kilobit
        self.bitsingbyte = 8589934592  # Bits in one gigabyte

        # Population data handler variables
        self.dataset_year = dataset_year
        self.one_km_res = one_km_res
        self.un_adjusted = un_adjusted
        self.data_dir = data_dir
        self.logs_dir = logs_dir

        # Logger
        self.enable_logging = enable_logging
        self.logger = None
        if self.enable_logging:
            self.logger = initialize_logger(self.logs_dir)

        # Assign loaded data to class attributes
        self.poi = poi
        self.cellsites = cellsites
        self.visibility = visibility
        self.area = area
        self.mbbt = pd.read_csv("https://zstagigaprodeuw1.blob.core.windows.net/gigainframapkit-public-container/mobile_capacity_data/MobileBB_Traffic_per_Subscr_per_Month.csv")
        self.mbbsubscr = pd.read_csv(
            "https://zstagigaprodeuw1.blob.core.windows.net/gigainframapkit-public-container/mobile_capacity_data/active-mobile-broadband-subscriptions.csv")
        self.mbbtraffic = pd.read_csv(
            "https://zstagigaprodeuw1.blob.core.windows.net/gigainframapkit-public-container/mobile_capacity_data/mobile-broadband-internet-traffic-within-the-country.csv")
        
        # Load bwdistance_km and bwdlachievbr data
        self.use_secure_files = use_secure_files
        if self.use_secure_files:
            # Load the secure files
            file_paths = {
                'bwdistance_km': os.path.join(self.data_dir, 'input_data', 'carrier_bandwidth', 'bwdistance_km.csv'),
                'bwdlachievbr_kbps': os.path.join(self.data_dir, 'input_data', 'carrier_bandwidth', 'bwdlachievbr_kbps.csv')
            }
            for key, path in file_paths.items():
                if not os.path.exists(path):
                    raise ValueError(f"File {key} not found in {path}")
            self.bwdistance_km = pd.read_csv(file_paths['bwdistance_km'])
            self.bwdlachievbr = pd.read_csv(file_paths['bwdlachievbr_kbps'])
        else:
            self.bwdistance_km = pd.read_csv("https://zstagigaprodeuw1.blob.core.windows.net/gigainframapkit-public-container/mobile_capacity_data/carrier_bandwidth/bwdistance_km.csv")
            self.bwdlachievbr = pd.read_csv("https://zstagigaprodeuw1.blob.core.windows.net/gigainframapkit-public-container/mobile_capacity_data/carrier_bandwidth/bwdlachievbr_kbps.csv") 

        # Set up the population data handler, and get population data
        self.population_data_handler = PopulationDataHandler(
            data_dir=os.path.join(self.data_dir, 'input_data', self.country_code, 'population'),
            country_code=self.country_code,
            dataset_year=self.dataset_year,
            one_km_res=self.one_km_res,
            un_adjusted=self.un_adjusted,
            logger=self.logger,
            enable_logging=self.enable_logging,
            logs_dir=self.logs_dir)
        self.population_data = self._get_population_data()

        # Set up the SRTM daa handler if required
        self.srtm_data_handler = None
        if visibility is None:
            self._log("info", "Setting up SRTM data handler...")
            self.srtm_data_handler = SRTMDataHandler(srtm_directory=os.path.join(self.data_dir, 'input_data', self.country_code, 'srtm1'),
                                                     enable_logging=self.enable_logging, logger=self.logger, logs_dir=self.logs_dir)
            self.srtm_data_handler.check_directory()  # Check if the SRTM directory exists, creates it if not

        # Set up the Visibility analysis if required
        if visibility is None:
            self._log("info", "Setting up visibility analysis...")
            self.visibility_analyzer = Visibility(
                points_of_interest=self.poi,
                cell_sites=self.cellsites,
                srtm_data_handler=self.srtm_data_handler,
                poi_antenna_height=self.poi_antenna_height,
                allowed_radio_types=['unknown', '2G', '3G', '4G', '5G'],
                earth_radius=6371,
                use_srtm=True,
                refraction_coef=0,
                logger=self.logger,
                logs_dir=self.logs_dir,
                enable_logging=self.enable_logging
            )

    def _get_population_data(self):
        """
        Property that loads and returns population data for the given country and year.
        """
        pop_gdf = self.population_data_handler.population_data
        pop_gdf = gpd.GeoDataFrame(pop_gdf["population"],
                                   geometry=gpd.points_from_xy(pop_gdf["lon"], pop_gdf["lat"]),
                                   crs="EPSG:4326")
        return pop_gdf

    def _log(self, level, message):
        """Conditionally log messages based on enable_logging flag."""
        if self.enable_logging and self.logger:
            if level == 'info':
                self.logger.info(message)
            elif level == 'warn':
                self.logger.warn(message)
            elif level == 'error':
                self.logger.error(message)
            elif level == 'debug':
                self.logger.debug(message)

    @property
    def bw(self):
        """
        Returns the total bandwidth in MHz.
        """
        return self.bw_L850 + self.bw_L1800 + self.bw_L2600

    @property
    def udatavmonth_pu(self):
        """
        Returns average mobile broadband user data traffic volume per month in GBs (Gigabytes) for the latest year in the ITU dataset.
        """
        return self.mbbt.loc[self.mbbt["entityIso_mbbsubscr"]
                             == self.country_code, "mbb_traffic_per_subscr_per_month"].item()

    @property
    def udatavmonth_year(self):
        """
        Returns average monthly mobile broadband user data traffic volume in gigabytes (GB).
        """
        return self.mbbt.loc[self.mbbt["entityIso_mbbsubscr"]
                             == self.country_code, "dataYear"].item()

    @property
    def nrb(self):
        """
        Returns the number of resource blocks.
        """
        return self.bw * self.rb_num_multiplier

    @property
    def avrbpdsch(self):
        """
        Returns the average number of RB available for PDSCH in units.
        """
        return ((100 - self.cco) / self.nrb) * 100

    def get_dl_bitrate(self, poi_distances):
        """
        Calculate the downlink bitrate based on the given POI distances.

        Parameters:
        - poi_distances (list, numpy array, or pandas Series): POI distances in meters.

        Returns:
        - np.ndarray: Array of downlink bitrates corresponding to each POI distance.

        Note:
        - `bwdistance_k` and `bwdlachievbr` are expected to be pandas DataFrames with columns
        named as `{bandwidth}MHz`.
        """
        # Convert input distances to numpy array
        poi_distances = np.array(poi_distances, dtype=float).flatten() / 1000  # converts distances in meters to kilometers

        # Create weights
        weights = np.array([self.bw_L850 / self.bw, self.bw_L1800 / self.bw, self.bw_L2600 / self.bw])

        # Array to populate
        dl_bitrates = np.full((len(poi_distances), 3), np.nan)

        for i, bw in enumerate(["L850", "L1800", "L2600"]):
            # Retrieve distance and bitrate arrays for the given bandwidth
            distances_array = self.bwdistance_km[bw].values.flatten()
            bitrate_array = self.bwdlachievbr[bw].values.flatten()

            # Create a mask to find the first distance in distances_array larger than or equal to each POI-tower distance
            mask = (distances_array[np.newaxis, :] >= poi_distances[:, np.newaxis])
            indices = mask.argmax(axis=1)

            # Identify POI distances that do not have a corresponding larger/equal distance in distances_array
            no_larger_equal = ~mask.any(axis=1)

            # Fetch the corresponding bitrate values and handle out-of-bound values
            dl_bitrate = bitrate_array[indices]
            dl_bitrate[no_larger_equal] = np.nan

            # Store the results
            dl_bitrates[:, i] = dl_bitrate

        # Compute the weighted sum of the downlink bitrates
        weighted_sum = np.dot(dl_bitrates, weights)

        return weighted_sum

    def poiddatareq(self, d):
        """
        Calculate the number of resource blocks required to meet the download throughput target for each distance.

        Parameters:
        - d (list, numpy array, or pandas Series): Distances from the tower in meters.

        Returns:
        - np.ndarray: Array of resource blocks required to meet the download throughput target for each distance.
                    Returns np.inf for distances exceeding max_radius or np.nan if an error occurs.
        """
        # Convert input to numpy array
        d = np.array(d, dtype=float).flatten()

        results = np.full(d.shape, np.nan)
        try:
            # Get the downlink bitrate for the given distances
            dl_bitrate = self.get_dl_bitrate(poi_distances=d)

            # Vectorized computation
            mask = d <= self.max_radius
            results[mask] = self.dlthtarg * 1024 / (dl_bitrate[mask] / self.avrbpdsch)
            results[~mask] = np.inf

            # Log the results
            for distance, rbdlthtarg in zip(d, results):
                self._log("debug", f'distance = {distance}, rbdlthtarg = {rbdlthtarg}')

        except ValueError as e:
            self._log("info", f"ValueError in poiddatareq: {e}")
        except Exception as e:
            self._log("info", f"An error occurred in poiddatareq: {e}")

        return results

    def brrbpopcd(self, popcd):
        """
        Bitrate per resource block at population center distance.

        Parameters:
        - popcd (int, float, list, numpy array, or pandas Series): Population center distance(s) in meters.

        Returns:
        - np.ndarray: Bitrate per resource block at population center distance(s) in kbps.
                    Returns np.nan for any errors encountered.
        """
        # Convert input to numpy array
        popcd = np.array(popcd, dtype=float).flatten()

        results = np.full(popcd.shape, np.nan)
        try:
            # Get the downlink bitrate for the given distances
            dl_bitrate = self.get_dl_bitrate(poi_distances=popcd)

            # Vectorized computation
            results = dl_bitrate / self.avrbpdsch

            # Log the results
            for distance, brrbpopcd_value in zip(popcd, results):
                self._log("debug", f'population centre distance = {distance}, brrbpopcd = {brrbpopcd_value}')

        except ValueError as e:
            self._log("info", f"ValueError in brrbpopcd: {e}")
        except Exception as e:
            self._log("info", f"An error occurred in brrbpopcd: {e}")

        return results

    def avubrnonbh(self, udatavmonth):
        """
        Average user bitrate in non-busy hour.

        Parameters:
        - udatavmonth (int): Average user data traffic volume per month in GB (Gigabyte)
        - nonbhu (int): Connection usage in non-busy hour in %

        Returns:
        - avubrnonbh (float): Average user bitrate in non-busy hour in kbps.

        Note:
        """
        # avubrnonbh = (((((((udatavmonth/days)/nbhours)*nonbhu/100)/minperhour)/secpermin)*bitsingbyte)/bitsinkbit)
        avubrnonbh = (
            ((((((udatavmonth /
                  self.days) /
                 self.nbhours) *
                self.nonbhu
                / 100) /
               self.minperhour) /
              self.secpermin) *
             self.bitsingbyte) /
            self.bitsinkbit)

        self._log("debug", f'avubrnonbh = {avubrnonbh}')

        return avubrnonbh

    def upopbr(self, avubrnonbh, pop):
        """
        Calculate User Population Bitrate per sector in kbps.

        This method computes the total bitrate required for a given population
        in a cell sector during non-busy hours, considering mobile broadband
        subscription rates and the operator's market share.

        Parameters:
        - avubrnonbh (float): Average user bitrate in non-busy hour in kbps.
        - pop (int): Total population in the area served by the cell sector.

        Returns:
        - float: User Population Bitrate in kbps.

        Note:
        This calculation uses class attributes mbb_subscr (mobile broadband
        subscription rate), oppopshare (operator's market share), and
        sectors_per_site (number of sectors per cell site).
        """
        upopbr = avubrnonbh * pop * (self.mbb_subscr / 100) * (self.oppopshare / 100) / self.sectors_per_site
        self._log("debug", f'upopbr = {upopbr}')

        return upopbr

    def upoprbu(self, upopbr, brrbpopcd):
        """
        User population resource blocks utilisation

        Parameters:
        - upopbr (float, int, or array-like): User Population Bitrate in kbps.
        - brrbpopcd (float, int, or array-like): Bitrate per resource block at population center distance in kbps.

        Returns:
        - np.ndarray: User population resource blocks utilisation in units.

        Note:
        If upopbr is a scalar and brrbpopcd is an array, the function will broadcast upopbr to match brrbpopcd's shape.
        """
        # Convert inputs to numpy arrays
        upopbr = np.array(upopbr, dtype=float).flatten()
        brrbpopcd = np.array(brrbpopcd, dtype=float).flatten()

        # Check if upopbr is a scalar (single value)
        if upopbr.size != 1 and upopbr.size != brrbpopcd.size:
            raise ValueError(f"upopbr must be a scalar or have the same size as brrbpopcd. upopbr size: {upopbr.size}, brrbpopcd size: {brrbpopcd.size}")

        # Calculate user population resource blocks utilisation in units.
        upoprbu = upopbr / brrbpopcd

        self._log("debug", f'upoprbu = {upoprbu}')
        return upoprbu

    def cellavcap(self, avrbpdsch, upoprbu):
        """
        Cell site available capacity check.

        Parameters:
        - avrbpdsch (float, int, or array-like): Resource blocks available for PDSCH, resource blocks.
        - upoprbu (float, int, or array-like): User population resource blocks utilisation, resource blocks.

        Returns:
        - np.ndarray: Shows available capacity at the cell site, resource blocks.

        Note:
        If avrbpdsch is a scalar and upoprbu is an array, the function will broadcast avrbpdsch to match upoprbu's shape.
        """
        # Convert inputs to numpy arrays
        avrbpdsch = np.array(avrbpdsch, dtype=float).flatten()
        upoprbu = np.array(upoprbu, dtype=float).flatten()

        # Check if avrbpdsch is a scalar (single value)
        if avrbpdsch.size != 1 and avrbpdsch.size != upoprbu.size:
            raise ValueError(f"avrbpdsch must be a scalar or have the same size as upoprbu. avrbpdsch size: {avrbpdsch.size}, upoprbu size: {upoprbu.size}")

        # Cell site available capacity calculation
        cellavcap = avrbpdsch - upoprbu

        self._log("debug", f'cellavcap = {cellavcap}')

        return cellavcap

    def sufcapch(self, cellavcap, rbdlthtarg):
        """
        Sufficient capacity check

        Parameters:
        - cellavcap (float, int, or array-like): Shows available capacity at the cell site, resource blocks.
        - rbdlthtarg (float, int, or array-like): RB number required to meet download throughput target in units.

        Returns:
        - np.ndarray: Boolean array showing whether capacity requirement is satisfied for each element.

        Note:
        If one input is a scalar and the other is an array, the function will broadcast the scalar to match the array's shape.
        """
        # Convert inputs to numpy arrays
        cellavcap = np.array(cellavcap, dtype=float).flatten()
        rbdlthtarg = np.array(rbdlthtarg, dtype=float).flatten()

        # Check if inputs have compatible sizes
        if cellavcap.size != 1 and rbdlthtarg.size != 1 and cellavcap.size != rbdlthtarg.size:
            raise ValueError(f"Inputs must have the same size or one must be a scalar. cellavcap size: {cellavcap.size}, rbdlthtarg size: {rbdlthtarg.size}")

        # Sufficient capacity check
        sufcapch = cellavcap > rbdlthtarg

        self._log("debug", f'sufcapch = {sufcapch}')
        return sufcapch

    def capacity_checker(self, d, popcd, udatavmonth, pop):
        """
        Performs a capacity check using the provided parameters.

        Parameters:
        - d (float): Distance to the Point of Interest (POI) for data rate calculation, in meters.
        - popcd (float): Population center distance parameter, in meters.
        - udatavmonth (float): Monthly data usage per user, in gigabytes.
        - pop (float): Population parameter.

        Returns:
        - tuple: A tuple containing:
            - float: User population bitrate (upopbr).
            - float: User population resource block utilization (upoprbu).
            - float: Available cell capacity (cellavcap).
            - float: Capacity check result (capcheck).

        This method calculates the following independent functions:
        - `rbdlthtarg`: Target data rate based on the distance `d`.
        - `brrpopcd`: Bitrate per resource block based on the population center distance `popcd`.
        - `avubrnonbh`: Average user bitrate based on the monthly data volume `udatavmonth`.

        It then calculates the following dependent functions:
        - `upopbr`: User population bitrate based on the average user bitrate `avubrnonbh` and the population `pop`.
        - `upoprbu`: User population resource block utilization based on the user population bitrate `upopbr` and the bitrate per resource block `brrpopcd`.
        - `cellavcap`: Available cell capacity based on `avrbpdsch` and `upoprbu`.
        - `capcheck`: Capacity sufficiency check based on `cellavcap` and the target data rate `rbdlthtarg`.
        """

        # Independent functions
        rbdlthtarg = self.poiddatareq(d)
        brrpopcd = self.brrbpopcd(popcd)
        avubrnonbh = self.avubrnonbh(udatavmonth)

        # Dependent functions
        upopbr = self.upopbr(avubrnonbh, pop)
        upoprbu = self.upoprbu(upopbr, brrpopcd)
        cellavcap = self.cellavcap(self.avrbpdsch, upoprbu)
        capcheck = self.sufcapch(cellavcap, rbdlthtarg)

        # Store and return the result
        dict_result = {"upopbr": upopbr, "upoprbu": upoprbu, "cellavcap": cellavcap, "capcheck": capcheck}
        return dict_result

    def calculate_buffer_areas(self):
        """
        Calculate buffer areas around cell sites and perform spatial analysis for network capacity assessment.

        This method performs the following key operations:
        1. Creates buffer areas and rings around cell sites using Voronoi polygons.
        2. Conducts visibility analysis between Points of Interest (POIs) and cell sites.
        3. Performs capacity calculations at POI, ring, and cell site levels.

        The method uses several geospatial operations:
        - Converts input data to GeoDataFrames
        - Projects data to an appropriate UTM CRS for accurate distance calculations
        - Creates Voronoi polygons to represent cell site service areas
        - Generates buffer areas and rings around cell sites
        - Performs spatial joins to associate POIs with cell sites and population data with rings

        Capacity calculations include:
        - Resource block requirements for download throughput targets
        - Bitrate per resource block at different distances
        - User population bitrate and resource block utilization
        - Available cell capacity and sufficiency checks

        Returns:
        tuple: A tuple containing two elements:
            - geodataframes (dict): A dictionary with two GeoDataFrames:
                - 'buffers': Buffer areas around cell sites
                - 'rings': Ring areas around cell sites
            - pois_within_cellsites (GeoDataFrame): POIs within cell site coverage areas,
            including capacity analysis results

        Note:
        - This method relies on several class attributes and methods for calculations.
        - The visibility analysis is performed only if pre-computed visibility data is not provided.
        - All output GeoDataFrames are reprojected to WGS84 (EPSG:4326) before being returned.

        Important class attributes used:
        - self.cellsites: Cell site data
        - self.poi: Points of Interest data
        - self.population_data: Population distribution data
        - self.visibility: Pre-computed visibility data (if available)
        - self.min_radius, self.max_radius, self.radius_step: Buffer configuration
        - self.area: Study area boundary
        """
        def _get_visibility_status(row):
            log_progress_bar(self.logger, row.name + 1, len(pois_within_cellsites), prefix='Visibility Analysis:', length=50)
            if pd.isna(row["ict_id"]):
                return np.nan, np.nan
            else:
                return self.visibility_analyzer.perform_pair_analysis(row["poi_id"], row["ict_id"])

        ### GEODATA PREPARATION ###

        # Copy input data
        cellsites = self.cellsites.data.copy()
        poi = self.poi.data.copy()
        population_gdf = self.population_data.copy()
        if self.visibility is not None:
            visibility = self.visibility.data.copy()

        # Create GeoDataFrames for cell sites and POIs
        cellsites_gdf = gpd.GeoDataFrame(
            cellsites, geometry=gpd.points_from_xy(cellsites.lon, cellsites.lat), crs=4326
        ).drop_duplicates(subset='ict_id')  # Drop duplicates in one step

        pois_gdf = gpd.GeoDataFrame(
            poi, geometry=gpd.points_from_xy(poi.lon, poi.lat), crs=4326
        )

        # Estimate UTM CRS and reproject the GeoDataFrames
        poi_utm = pois_gdf.estimate_utm_crs()
        for gdf in [pois_gdf, population_gdf, cellsites_gdf]:
            gdf.to_crs(poi_utm, inplace=True)

        ### CREATE BUFFERS AND RINGS AROUND EACH CELL SITE ###

        # Create Voronoi polygons for the cell sites
        cellsites_gdf = create_voronoi_cells(cellsites_gdf, self.area)

        # Generate buffers, rings, and clipped areas
        for radius in range(self.min_radius, self.max_radius + 1, self.radius_step):
            buffer_col = f'buffer_{radius}'
            ring_col = f'ring_{radius}'
            clring_col = f'clring_{radius}'
            clbuffer_col = f'clbuffer_{radius}'

            # Create buffer areas
            cellsites_gdf[buffer_col] = cellsites_gdf.geometry.buffer(radius)

            # Create rings based on buffer differences
            if radius == self.min_radius:
                cellsites_gdf[ring_col] = cellsites_gdf[buffer_col]
            else:
                prev_buffer = f'buffer_{radius - self.radius_step}'
                cellsites_gdf[ring_col] = cellsites_gdf[buffer_col].difference(cellsites_gdf[prev_buffer])

            # Intersect rings and buffers with Voronoi polygons
            cellsites_gdf[clring_col] = cellsites_gdf.apply(lambda row: row[ring_col].intersection(row.voronoi_polygons), axis=1)
            cellsites_gdf[clbuffer_col] = cellsites_gdf.apply(lambda row: row[buffer_col].intersection(row.voronoi_polygons), axis=1)

        # Convert clipped buffers to long format (only for the maximum radius buffer)
        buffers_gdf = cellsites_gdf[['ict_id', f'clbuffer_{self.max_radius}']].rename(columns={f'clbuffer_{self.max_radius}': 'geometry'})
        buffers_gdf = gpd.GeoDataFrame(buffers_gdf, geometry='geometry', crs=poi_utm)

        # Convert clipped rings to long format
        rings_columns = ['ict_id'] + [col for col in cellsites_gdf.columns if col.startswith('clring')]
        rings_gdf = cellsites_gdf[rings_columns].melt(id_vars='ict_id', var_name='buffer_column', value_name='geometry')
        rings_gdf['buffer'] = rings_gdf['buffer_column'].str.extract(r'(\d+)').astype(int)
        rings_gdf = gpd.GeoDataFrame(rings_gdf.drop('buffer_column', axis=1), geometry='geometry', crs=poi_utm)
        rings_gdf['radius'] = rings_gdf['buffer'] - self.radius_step / 2

        ### VISIBILITY ANALYSIS ###

        # If visibility analysis is not provided
        if self.visibility is None:
            # Match POIs to cell towers based on coverage area
            pois_within_cellsites = gpd.sjoin(pois_gdf, buffers_gdf, how='left', predicate='within')
            pois_within_cellsites = pois_within_cellsites.drop_duplicates(subset='poi_id', keep='first')  # Drop duplicates in one step, but should not happen because of Voronoi cells
            pois_within_cellsites = pois_within_cellsites[["poi_id", "lat", "lon", "ict_id"]]
            # Assess whether the POI is visible from the cell site
            pois_within_cellsites["ground_distance"], pois_within_cellsites["is_visible"] = zip(*pois_within_cellsites.apply(_get_visibility_status, axis=1))
        # If visibility analysis results are provided, no need to launch visibility analysis
        else:
            # Match POIs to cell towers based on coverage area
            visibility_filtered = visibility.loc[visibility["order"] == 1, ["poi_id", "ground_distance", "is_visible", "ict_id"]]
            pois_within_cellsites = pois_gdf[["poi_id", "lat", "lon"]].merge(visibility_filtered, on="poi_id", how="left")

        ### POI-LEVEL COMPUTATIONS ###

        # Number of resource blocks required to meet the download throughput target for each distance
        pois_within_cellsites["rbdlthtarg"] = self.poiddatareq(pois_within_cellsites["ground_distance"])

        ### RING-LEVEL COMPUTATIONS AROUND EACH CELL SITE ###

        # Bitrate per resource block at population center distance
        rings_gdf["brrbpopcd"] = rings_gdf["radius"].map(self.brrbpopcd).apply(lambda x: x[0])
        # Get population per ring
        population_join = gpd.sjoin(population_gdf, rings_gdf, how='inner', predicate='within')
        population_join = population_join.groupby(['ict_id', 'buffer']).agg({'population': 'sum'}).reset_index()
        rings_gdf = rings_gdf.merge(population_join, on=['ict_id', 'buffer'], how='left')
        rings_gdf["population"] = rings_gdf["population"].fillna(0)
        # User population bitrate per ring
        rings_gdf["upopbr"] = self.upopbr(self.avubrnonbh(self.udatavmonth_pu), rings_gdf["population"])
        # User population resource blocks utilisation
        rings_gdf["upoprbu"] = self.upoprbu(rings_gdf["upopbr"], rings_gdf["brrbpopcd"])

        ### CELL SITE-LEVEL COMPUTATIONS ###

        # Sum all rings for each cell site, yielding the total resource blocks utilisation per cell site
        cellsites_rbu = rings_gdf.groupby('ict_id')["upoprbu"].sum().reset_index()
        cellsites_rbu["cellavcap"] = cellsites_rbu["upoprbu"].apply(lambda row: self.cellavcap(self.avrbpdsch, row)[0])

        ### MERGE POI AND CELL SITE ###

        pois_within_cellsites = pois_within_cellsites.merge(cellsites_rbu, on='ict_id', how='left')
        pois_within_cellsites["cellavcap"] = pois_within_cellsites["cellavcap"].fillna(0)
        pois_within_cellsites["sufcapch"] = self.sufcapch(pois_within_cellsites["cellavcap"], pois_within_cellsites["rbdlthtarg"])
        pois_within_cellsites = pois_within_cellsites[["poi_id", "lat", "lon", "ict_id", "ground_distance", "is_visible", "rbdlthtarg", "upoprbu", "cellavcap", "sufcapch"]]

        ### PREPARE OUTPUT ###
       
       # Export as GeoDataFrames in WGS84
        pois_within_cellsites = gpd.GeoDataFrame(
            pois_within_cellsites,
            geometry=gpd.points_from_xy(pois_within_cellsites["lon"], pois_within_cellsites["lat"]),
            crs=poi_utm)
        for gdf in [buffers_gdf, rings_gdf, pois_within_cellsites]:
            gdf.to_crs(4326, inplace=True)

        # Package rings and buffer geodata into a single dictionary
        geodataframes = {"buffers": buffers_gdf, "rings": rings_gdf}

        return geodataframes, pois_within_cellsites

    def mbbtps(self):
        """
        Reads rows with the latest year data available for both
        mobile-broadband Internet traffic (within the country) and active mobile-broadband subscriptions
        and calculates Mobile broadband internet traffic (within the country) per active mobile broadband subscription
        per month.

        Parameters:
        - mbbsubscr (dataframe): Active mobile broadband subscriptions (ITU, https://datahub.itu.int/data/?i=11632)
        - mbbtraffic (dataframe): Mobile broadband internet traffic (within the country) in Exabytes (ITU, https://datahub.itu.int/data/?i=13068)

        Returns:
        - DataFrame containing mobile broadband internet traffic per subscription per month column in Gigabytes.
        """
        # Combine data tables
        df = pd.merge(self.mbbsubscr, self.mbbtraffic, on=[
                      'entityName', 'dataYear'], suffixes=('_mbbsubscr', '_mbbtraffic'))

        filtered_data = df[(df['dataValue_mbbsubscr'] != 0)
                           & (df['dataValue_mbbtraffic'] != 0)]

        # Group by `entityName` and find the latest `dataYear` for each group
        latest_years = filtered_data.groupby(
            'entityName')['dataYear'].max().reset_index()

        # Filter the original DataFrame
        # Join the DataFrame of latest years back to the filtered DataFrame
        # to get only the rows for the latest year of each entity with non-zero `dataValue`
        df = pd.merge(filtered_data, latest_years,
                      on=['entityName', 'dataYear'])

        # Calculate mobile broadband internet traffic per subscription per month column in Gigabytes.
        df['mbb_traffic_per_subscr_per_month'] = df['dataValue_mbbtraffic'] * \
            1024**3 / df['dataValue_mbbsubscr'] / 12

        # Select relevant columns
        df = df.loc[:, ['entityName', 'entityIso_mbbsubscr', 'dataValue_mbbsubscr',
                        'dataValue_mbbtraffic', 'mbb_traffic_per_subscr_per_month', 'dataYear']]

        # Store the result
        self.mbbtps_result = df
        return df
