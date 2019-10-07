"""
.. module: electricity.py

"""
from pathlib import Path
from inspect import currentframe, getframeinfo
import numpy as np
import csv
from wurst import searching as ws
from wurst.ecoinvent import filters
from wurst.geo import geomatcher
import wurst
from .activity_maps import InventorySet
import uuid

REGION_MAPPING_FILEPATH = Path(getframeinfo(currentframe()).filename).resolve().parent.joinpath('data/'+ 'regionmappingH12.csv')
POPULATION_PER_COUNTRY = Path(getframeinfo(currentframe()).filename).resolve().parent.joinpath('data/'+ 'population_per_country.csv')
LHV_FUELS = Path(getframeinfo(currentframe()).filename).resolve().parent.joinpath('data/'+ 'fuels_lower_heating_value.txt')

class Electricity:
    """
    Class that modifies electricity markets in ecoinvent based on REMIND output data.

    :ivar scenario: name of a Remind scenario
    :vartype scenario: str

    """

    def __init__(self, db, rmd, scenario, year):
        self.db = db
        self.rmd = rmd
        self.geo = self.get_REMIND_geomatcher()
        self.population = self.get_population_dict()
        self.scenario = scenario
        self.year = year
        self.fuels_lhv = self.get_lower_heating_values()
        mapping = InventorySet(self.db)
        self.activities_map = mapping.activities_map
        self.powerplant_map = mapping.powerplants_map
        self.emissions_map = mapping.emissions_map

    def get_lower_heating_values(self):
        """
        Loads a csv file into a dictionary. This dictionary contains lower heating values for a number of fuel types.
        Taken from: https://www.engineeringtoolbox.com/fuels-higher-calorific-values-d_169.html

        :return: dictionary that contains lower heating values
        :rtype: dict
        """
        if not LHV_FUELS.is_file():
            raise FileNotFoundError('The dictionary of lower heating values could not be found.')

        with open(LHV_FUELS) as f:
            return dict(filter(None, csv.reader(f, delimiter=';')))

    def get_REMIND_geomatcher(self):
        """
        Load a geomatcher object from the `constructive_geometries`library and add definitions.
        It is used to find correspondences between REMIND and ecoinvent region names.
        :return: geomatcher object
        :rtype: wurst.geo.geomatcher
        """
        if not REGION_MAPPING_FILEPATH.is_file():
            raise FileNotFoundError('The mapping file for region names could not be found.')

        with open(REGION_MAPPING_FILEPATH) as f:
            f.readline()
            csv_list = [[val.strip() for val in r.split(";")] for r in f.readlines()]
            l = [(x[1], x[2]) for x in csv_list]


        # List of countries not found
        countries_not_found = ["CC", "CX", 'GG', 'JE', 'BL']

        rmnd_to_iso = {}
        iso_to_rmnd = {}
        # Build a dictionary that maps region names (used by REMIND) to ISO country codes
        # And a reverse dictionary that maps ISO country codes to region names
        for ISO, region in l:
            if ISO not in countries_not_found:
                try:
                    rmnd_to_iso[region].append(ISO)
                except KeyError:
                    rmnd_to_iso[region] = [ISO]

                iso_to_rmnd[region] = ISO

        geo = geomatcher
        geo.add_definitions(rmnd_to_iso, "REMIND")

        return geo

    def remind_to_ecoinvent_location(self, location):
        """
        Find the corresponding ecoinvent region given a REMIND region.

        :param location: name of a REMIND region
        :type location: str
        :return: name of an ecoinvent region
        :rtype: str
        """

        if location != "World":
            location = ('REMIND', location)

            ecoinvent_locations =[]
            try:
                for r in self.geo.intersects(location):
                    if not isinstance(r, tuple):
                        ecoinvent_locations.append(r)
                return ecoinvent_locations
            except KeyError as e:
                print("Can't find location {} using the geomatcher.".format(location))

        else:
            return "GLO"

    def ecoinvent_to_remind_location(self, location):
        """
        Return a REMIND region name for a 2-digit ISO country code given.
        Set rules in case two REMIND regions are within the ecoinvent region.

        :param location: 2-digit ISO country code
        :type location: str
        :return: REMIND region name
        :rtype: str
        """

        if location == 'GLO':
            return ['World']

        if location == 'RoW':
            return ['CAZ']

        if location == 'IAI Area, Russia & RER w/o EU27 & EFTA':
            return ['REF']

        remind_location = [r[1] for r in self.geo.within(location) if r[0] == 'REMIND' and r[1] != 'World']

        # If we have more than one REMIND region
        if len(remind_location)>1:
            # TODO: find a more elegant way to do that
            # We need to find the most specific REMIND region
            if len(set(remind_location).intersection(set(('EUR', 'NEU')))) == 2:
                remind_location.remove('EUR')
            if len(set(remind_location).intersection(set(('EUR', 'REF')))) == 2:
                remind_location.remove('EUR')
            if len(set(remind_location).intersection(set(('OAS', 'IND')))) == 2:
                remind_location.remove('OAS')
            if len(set(remind_location).intersection(set(('OAS', 'JPN')))) == 2:
                remind_location.remove('OAS')
            if len(set(remind_location).intersection(set(('AFR', 'SSA')))) == 2:
                remind_location.remove('AFR')
            if len(set(remind_location).intersection(set(('USA', 'CAZ')))) == 2:
                remind_location.remove('USA')
            if len(set(remind_location).intersection(set(('OAS', 'CHA')))) == 2:
                remind_location.remove('OAS')
            if len(set(remind_location).intersection(set(('AFR', 'MEA')))) == 2:
                remind_location.remove('AFR')
            if len(set(remind_location).intersection(set(('OAS', 'MEA')))) == 2:
                remind_location.remove('OAS')
            if len(set(remind_location).intersection(set(('OAS', 'REF')))) == 2:
                remind_location.remove('OAS')
            if len(set(remind_location).intersection(set(('OAS', 'EUR')))) == 2:
                remind_location.remove('OAS')

            return remind_location

        elif len(remind_location) == 0:
            print('no loc for {}'.format(location))

        else:
            return remind_location


    def get_suppliers_of_a_region(self, ecoinvent_regions, ecoinvent_technologies):
        """
        Return a list of electricity-producing datasets which location and name correspond to the region and name given,
        respectively.

        :param ecoinvent_regions: an ecoinvent region
        :type ecoinvent_regions: str
        :param ecoinvent_technologies: name of ecoinvent dataset
        :type ecoinvent_technologies: str
        :return: list of wurst datasets
        :rtype: list
        """

        return ws.get_many(self.db,
                                 *[ws.either(*[ws.equals('name', supplier) for supplier in ecoinvent_technologies]),
                                   ws.either(*[ws.equals('location', loc) for loc in ecoinvent_regions]),
                                   ws.equals('unit', 'kilowatt hour')])

    def get_population_dict(self):
        """
        Create a dictionnary with ISO country codes as keys and population count as values.
        :return: ISO country code to population count dictionnary
        :rtype: dict
        """

        if not POPULATION_PER_COUNTRY.is_file():
            raise FileNotFoundError('The population per country dictionary file could not be found.')

        with open(POPULATION_PER_COUNTRY) as f:
            return dict(filter(None, csv.reader(f, delimiter=';')))

    def get_pop_weighted_share(self, supplier, suppliers):
        """
        Return the share of population of a region where an electricity-producing dataset is located,
        relative to the summed population of regions of a list of datasets.

        :param supplier: electricity-producing dataset
        :type supplier: wurst dataset
        :param suppliers: list of electricity-producing datasets
        :type suppliers: list of wurst datasets
        :return: share of population relative to the total population
        :rtype: float
        """
        loc_population = int(self.population.get(supplier['location'],0))

        locs_population = 0

        for loc in suppliers:
            locs_population += int(self.population.get(loc['location'],0))

        return loc_population/locs_population

    def create_new_markets_low_voltage(self):
        """
        Create low voltage market groups for electricity, by receiving medium voltage market groups as inputs
        and adding transformation and distribution losses.
        Contribution from solar power is added here as well.
        Does not return anything. Modifies the database in place.
        """
        # Loop through REMIND regions
        gen_region = (region for region in self.rmd.electricity_markets.coords['region'].values)

        for region in gen_region:
            # Create an empty dataset
            new_dataset = {}
            new_dataset['location'] = region
            new_dataset['name'] = 'market group for electricity, low voltage, ' + self.scenario + ', ' + str(self.year)
            new_dataset['reference product'] = 'electricity, low voltage'
            new_dataset['unit'] = 'kilowatt hour'
            new_dataset['database'] = self.db[1]['database']
            new_dataset['code'] = str(uuid.uuid4().hex)
            new_dataset['comment'] = 'Dataset produced from REMIND scenario output results'

            # First, add the reference product exchange
            new_exchanges = []
            new_exchanges.append(
                {
                    'uncertainty type': 0,
                    'loc': 1,
                    'amount': 1,
                    'type': 'production',
                    'production volume': 0,
                    'product': 'electricity, low voltage',
                    'name': 'market group for electricity, low voltage, ' + self.scenario + ', ' + str(self.year),
                    'unit': 'kilowatt hour',
                    'location': region
                }
            )

            # Second, add an input to of sulfur hexafluoride emission to compensate the transformer's leakage
            # And an emission of a corresponding amount
            new_exchanges.append(
                    {
                    'uncertainty type': 0,
                    'loc': 2.99e-9,
                    'amount': 2.99e-9,
                    'type': 'technosphere',
                    'production volume': 0,
                    'product': 'sulfur hexafluoride, liquid',
                    'name': 'market for sulfur hexafluoride, liquid',
                    'unit': 'kilogram',
                    'location': 'RoW'
                    }
                )
            new_exchanges.append(
                    {
                    'uncertainty type': 0,
                    'loc': 2.99e-9,
                    'amount': 2.99e-9,
                    'type': 'biosphere',
                    'input': ('biosphere3', '35d1dff5-b535-4628-9826-4a8fce08a1f2'),
                   'name': 'Sulfur hexafluoride',
                   'unit': 'kilogram',
                   'categories': ('air', 'non-urban air or from high stacks')
                    }
                )

            # Third, transmission line
            new_exchanges.append(
                    {
                    'uncertainty type': 0,
                    'loc': 8.74e-8,
                    'amount': 8.74e-8,
                    'type': 'technosphere',
                    'production volume': 0,
                    'product': 'distribution network, electricity, low voltage',
                    'name': 'distribution network construction, electricity, low voltage' ,
                    'unit': 'kilometer',
                    'location': 'RoW'
                    }
                )

            # Fourth, add the contribution of solar power
            solar_amount = 0
            gen_tech = list((tech for tech in self.rmd.electricity_markets.coords['variable'].values if "Solar" in tech))
            for technology in gen_tech:
                # If the solar power technology contributes to the mix
                    if self.rmd.electricity_markets.loc[technology,region,0] != 0.0:
                        # Fetch ecoinvent regions contained in the REMIND region
                        ecoinvent_regions = self.remind_to_ecoinvent_location(region)

                        # Contribution in supply
                        amount = self.rmd.electricity_markets.loc[technology, region, 0].values
                        solar_amount += amount

                        # Get the possible names of ecoinvent datasets
                        ecoinvent_technologies = self.powerplant_map[self.rmd.rev_electricity_market_labels[technology]]

                        # Fetch electricity-producing technologies contained in the REMIND region
                        suppliers = list(self.get_suppliers_of_a_region(ecoinvent_regions, ecoinvent_technologies))

                        # If no technology is available for the REMIND region
                        if len(suppliers) == 0:
                            # We fetch European technologies instead
                            suppliers = list(self.get_suppliers_of_a_region(['RER'], ecoinvent_technologies))

                        # If, after looking for European technologies, no technology is available
                        if len(suppliers) == 0:
                            # We fetch RoW technologies instead
                            suppliers = list(self.get_suppliers_of_a_region(['RoW'], ecoinvent_technologies))

                        for supplier in suppliers:
                            share = self.get_pop_weighted_share(supplier, suppliers)
                            new_exchanges.append(
                                    {
                                        'uncertainty type': 0,
                                        'loc': (amount * share),
                                        'amount': (amount * share) ,
                                        'type': 'technosphere',
                                        'production volume': 0,
                                        'product': supplier['reference product'],
                                        'name': supplier['name'],
                                        'unit': supplier['unit'],
                                        'location': supplier['location']
                                    }
                                )
            # Fifth, add:
            # * an input from the medium voltage market minus solar contribution, including transformation loss
            # * an self-consuming input for transmission loss
            new_exchanges.append(
                {
                'uncertainty type': 0,
                'loc': (1- solar_amount) * 1.0276,
                'amount': (1- solar_amount) * 1.0276,
                'type': 'technosphere',
                'production volume': 0,
                'product': 'electricity, medium voltage',
                'name': 'market group for electricity, medium voltage, ' + self.scenario + ', ' + str(self.year) ,
                'unit': 'kilowatt hour',
                'location': region
                }
            )

            new_exchanges.append(
                {
                'uncertainty type': 0,
                'loc': 0.0298,
                'amount': 0.0298,
                'type': 'technosphere',
                'production volume': 0,
                'product': 'electricity, low voltage',
                'name': 'market group for electricity, low voltage, ' + self.scenario + ', ' + str(self.year) ,
                'unit': 'kilowatt hour',
                'location': region
                }
            )

            new_dataset['exchanges'] = new_exchanges
            self.db.append(new_dataset)

    def create_new_markets_medium_voltage(self):
        """
        Create medium voltage market groups for electricity, by receiving high voltage market groups as inputs
        and adding transformation and distribution losses.
        Contribution from solar power is added in low voltage market groups.
        Does not return anything. Modifies the database in place.
        """
        # Loop through REMIND regions
        gen_region = (region for region in self.rmd.electricity_markets.coords['region'].values)

        for region in gen_region:
            # Create an empty dataset
            new_dataset = {}
            new_dataset['location'] = region
            new_dataset['name'] = 'market group for electricity, medium voltage, ' + self.scenario + ', ' + str(self.year)
            new_dataset['reference product'] = 'electricity, medium voltage'
            new_dataset['unit'] = 'kilowatt hour'
            new_dataset['database'] = self.db[1]['database']
            new_dataset['code'] = str(uuid.uuid1().hex)
            new_dataset['comment'] = 'Dataset produced from REMIND scenario output results'

            # First, add the reference product exchange
            new_exchanges = []
            new_exchanges.append(
                {
                    'uncertainty type': 0,
                    'loc': 1,
                    'amount': 1,
                    'type': 'production',
                    'production volume': 0,
                    'product': 'electricity, medium voltage',
                    'name': 'market group for electricity, medium voltage, ' + self.scenario + ', ' + str(self.year),
                    'unit': 'kilowatt hour',
                    'location': region
                }
            )

            # Second, add:
            # * an input from the high voltage market, including voltage transformation loss
            # * an self-consuming input for transmission loss
            new_exchanges.append(
                {
                'uncertainty type': 0,
                'loc': 1.0062,
                'amount': 1.0062,
                'type': 'technosphere',
                'production volume': 0,
                'product': 'electricity, high voltage',
                'name': 'market group for electricity, high voltage, ' + self.scenario + ', ' + str(self.year) ,
                'unit': 'kilowatt hour',
                'location': region
                }
            )

            new_exchanges.append(
                {
                'uncertainty type': 0,
                'loc': 0.0041,
                'amount': 0.0041,
                'type': 'technosphere',
                'production volume': 0,
                'product': 'electricity, medium voltage',
                'name': 'market group for electricity, medium voltage, ' + self.scenario + ', ' + str(self.year) ,
                'unit': 'kilowatt hour',
                'location': region
                }
            )

            # Third, add an input to of sulfur hexafluoride emission to compensate the transformer's leakage
            # And an emission of a corresponding amount
            new_exchanges.append(
                    {
                    'uncertainty type': 0,
                    'loc': 5.4e-8,
                    'amount': 5.4e-8,
                    'type': 'technosphere',
                    'production volume': 0,
                    'product': 'sulfur hexafluoride, liquid',
                    'name': 'market for sulfur hexafluoride, liquid' ,
                    'unit': 'kilogram',
                    'location': 'RoW'
                    }
                )
            new_exchanges.append(
                    {
                    'uncertainty type': 0,
                    'loc': 5.4e-8,
                    'amount': 5.4e-8,
                    'type': 'biosphere',
                    'input': ('biosphere3', '35d1dff5-b535-4628-9826-4a8fce08a1f2'),
                   'name': 'Sulfur hexafluoride',
                   'unit': 'kilogram',
                   'categories': ('air', 'non-urban air or from high stacks')
                    }
                )

            # Fourth, transmission line
            new_exchanges.append(
                    {
                    'uncertainty type': 0,
                    'loc': 1.8628e-8,
                    'amount': 1.8628e-8,
                    'type': 'technosphere',
                    'production volume': 0,
                    'product': 'transmission network, electricity, medium voltage',
                    'name': 'transmission network construction, electricity, medium voltage' ,
                    'unit': 'kilometer',
                    'location': 'RoW'
                    }
                )

            new_dataset['exchanges'] = new_exchanges
            self.db.append(new_dataset)

    def create_new_markets_high_voltage(self):
        """
        Create high voltage market groups for electricity, based on electricity mixes given by REMIND.
        Contribution from solar power is added in low voltage market groups.
        Does not return anything. Modifies the database in place.
        """
        # Loop through REMIND regions
        gen_region = (region for region in self.rmd.electricity_markets.coords['region'].values)
        gen_tech = list((tech for tech in self.rmd.electricity_markets.coords['variable'].values if "Solar" not in tech))
        
        for region in gen_region:
            # Fetch ecoinvent regions contained in the REMIND region
            ecoinvent_regions = self.remind_to_ecoinvent_location(region)

            # Create an empty dataset
            new_dataset = {}
            new_dataset['location'] = region
            new_dataset['name'] = 'market group for electricity, high voltage, ' + self.scenario + ', ' + str(self.year)
            new_dataset['reference product'] = 'electricity, high voltage'
            new_dataset['unit'] = 'kilowatt hour'
            new_dataset['database'] = self.db[1]['database']
            new_dataset['code'] = str(uuid.uuid4().hex)
            new_dataset['comment'] = 'Dataset produced from REMIND scenario output results'

            new_exchanges = []

            # First, add the reference product exchange
            new_exchanges.append(
                        {
                            'uncertainty type': 0,
                            'loc': 1,
                            'amount': 1,
                            'type': 'production',
                            'production volume': 0,
                            'product': 'electricity, high voltage',
                            'name': 'market group for electricity, high voltage, ' + self.scenario + ', ' + str(self.year),
                            'unit': 'kilowatt hour',
                            'location': region
                        }
                    )

            # Loop through the REMIND technologies
            for technology in gen_tech:

                # If the given technology contributes to the mix
                if self.rmd.electricity_markets.loc[technology,region,0] != 0.0:

                    # Contribution in supply
                    amount = self.rmd.electricity_markets.loc[technology, region, 0].values

                    # Get the possible names of ecoinvent datasets
                    ecoinvent_technologies = self.powerplant_map[self.rmd.rev_electricity_market_labels[technology]]

                    # Fetch electricity-producing technologies contained in the REMIND region
                    suppliers = list(self.get_suppliers_of_a_region(ecoinvent_regions, ecoinvent_technologies))

                    # If no technology is available for the REMIND region
                    if len(suppliers) == 0:
                        # We fetch European technologies instead
                        suppliers = list(self.get_suppliers_of_a_region(['RER'], ecoinvent_technologies))

                    # If, after looking for European technologies, no technology is available
                    if len(suppliers) == 0:
                        # We fetch RoW technologies instead
                        suppliers = list(self.get_suppliers_of_a_region(['RoW'], ecoinvent_technologies))

                    for supplier in suppliers:
                        share = self.get_pop_weighted_share(supplier, suppliers)
                        new_exchanges.append(
                                {
                                    'uncertainty type': 0,
                                    'loc': (amount * share),
                                    'amount': (amount * share) ,
                                    'type': 'technosphere',
                                    'production volume': 0,
                                    'product': supplier['reference product'],
                                    'name': supplier['name'],
                                    'unit': supplier['unit'],
                                    'location': supplier['location']
                                }
                            )
            new_dataset['exchanges'] = new_exchanges
            self.db.append(new_dataset)

    def relink_activities_to_new_markets(self):
        """
        Links electricity input exchanges to new datasets with the appropriate REMIND location:
        * "market for electricity, high voltage" --> "market group for electricity, high voltage"
        * "market for electricity, medium voltage" --> "market group for electricity, medium voltage"
        * "market for electricity, low voltage" --> "market group for electricity, low voltage"
        Does not return anything.
        """

        # Filter all activities that consume high voltage electricity
        #electricity_market_filter = [ws.either(*[ws.doesnt_contain('name', 'market group for electricity')])]

        for ds in ws.get_many(self.db, ws.exclude(ws.contains('name', 'market group for electricity'))):

            for exc in ws.get_many(ds['exchanges'],
               *[ws.either(*[ws.contains('unit', 'kilowatt hour'),
                    ws.contains('name','market for electricity'),
                      ws.contains('name','electricity voltage transformation'),
                             ws.contains('name', 'market group for electricity')])]):
                if exc['type'] != 'production' and exc['unit'] == 'kilowatt hour':
                    if "high" in exc['product']:
                        exc['name'] = 'market group for electricity, high voltage, ' + self.scenario + ', ' + str(self.year)
                        exc['product'] = 'electricity, high voltage'
                        exc['location'] = self.ecoinvent_to_remind_location(exc['location'])[0]
                    if "medium" in exc['product']:
                        exc['name'] = 'market group for electricity, medium voltage, ' + self.scenario + ', ' + str(self.year)
                        exc['product'] = 'electricity, medium voltage'
                        exc['location'] = self.ecoinvent_to_remind_location(exc['location'])[0]
                    if "low" in exc['product']:
                        exc['name'] = 'market group for electricity, low voltage, ' + self.scenario + ', ' + str(self.year)
                        exc['product'] = 'electricity, low voltage'
                        exc['location'] = self.ecoinvent_to_remind_location(exc['location'])[0]

    def find_ecoinvent_fuel_efficiency(self, ds, fuel_filters):
        """
        This method calculates the efficiency value set initially, in case it is not specified in the parameter
        field of the dataset. In Carma datasets, fuel inputs are expressed in megajoules instead of kilograms.

        :param ds: a wurst dataset of an electricity-producing technology
        :param fuel_filters: wurst filter to to filter fule input exchanges
        :return: the efficiency value set by ecoinvent
        """

        if 'ecoinvent' in ds['database']:
            not_allowed = ['thermal']
            key = list(key for key in ds['parameters'] if 'efficiency' in key and not any(item in key for item in not_allowed))
            if len(key) > 0:
                return ds['parameters'][key[0]]

            else:
                energy_input = np.sum(np.sum(np.asarray([[float(self.fuels_lhv[k]) / 3.6 * exc['amount']
                                                   for exc in ws.technosphere(ds, *fuel_filters)
                                                   if k in exc['name']] for k in self.fuels_lhv])))

                ds['parameters']['efficiency'] = float(ws.reference_product(ds)['amount']) / energy_input
                return ds['parameters']['efficiency']

        else:

            energy_input = np.sum([exc['amount'] / 3.6 for exc in ws.technosphere(ds, *fuel_filters)])

            ds['parameters'] = {}
            ds['parameters']['efficiency'] = float(ws.reference_product(ds)['amount']) / energy_input

            return ds['parameters']['efficiency']


    def find_fuel_efficiency_scaling_factor(self, ds, fuel_filters, technology):
        """
        This method calculates a scaling factor to change the process efficiency set by ecoinvent
        to the efficiency given by REMIND.

        :param ds: wurst dataset of an electricity-producing technology
        :param fuel_filters: wurst filter to filter the fuel input exchanges
        :param technology: label of an electricity-producing technology
        :return: a rescale factor to change from ecoinvent efficiency to REMIND efficiency
        :rtype: float
        """

        ecoinvent_eff = self.find_ecoinvent_fuel_efficiency(ds, fuel_filters)
        remind_locations= self.ecoinvent_to_remind_location(ds['location'])
        remind_eff = self.rmd.electricity_efficiencies.loc[dict(
            variable=self.rmd.electricity_efficiency_labels[technology],
            region=remind_locations,
            value=0
        )].mean().values

        return ecoinvent_eff / remind_eff

    def update_ecoinvent_efficiency_parameter(self, ds, scaling_factor):
        """
        Update the old efficiency value in the ecoinvent dataset by the newly calculated one.
        :param ds: dataset
        :type ds: dict
        :param scaling_factor: scaling factor (new efficiency / old efficiency)
        :type scaling_factor: float
        """
        parameters = ds['parameters']
        possibles = ['efficiency', 'efficiency_oil_country', 'efficiency_electrical']


        for key in possibles:
            if key in parameters:
                ds['parameters'][key] /= scaling_factor


    def get_remind_mapping(self):
        """
        Define filter functions that decide which wurst datasets to modify.
        :return: dictionary that contains filters and functions
        :rtype: dict
        """

        #

        generic_excludes = [
            ws.exclude(ws.contains('name', 'aluminium industry')),
            ws.exclude(ws.contains('name', 'carbon capture and storage')),
            ws.exclude(ws.contains('name', 'market'))
        ]
        no_imports = [ws.exclude(ws.contains('name', 'import'))]

        gas_open_cycle_electricity = [
            ws.equals('name', 'electricity production, natural gas, conventional power plant')]

        biomass_chp_electricity = [
                ws.either(ws.contains('name', ' wood'), ws.contains('name', 'bio')),
                ws.equals('unit', 'kilowatt hour'),
                ws.contains('name', 'heat and power co-generation')]

        coal_IGCC = [
            ws.either(ws.contains('name', 'coal'), ws.contains('name', 'lignite')),
            ws.contains('name', 'IGCC'),
            ws.contains('name', 'pre'),
            ws.contains('name', 'no CCS'),
            ws.equals('unit', 'kilowatt hour'),
        ]

        coal_IGCC_CCS = [
            ws.either(ws.contains('name', 'coal'), ws.contains('name', 'lignite')),
            ws.contains('name', 'storage'),
            ws.contains('name', 'pre'),
            ws.equals('unit', 'kilowatt hour'),
        ]

        coal_PC_CCS = [
            ws.either(ws.contains('name', 'coal'), ws.contains('name', 'lignite')),
            ws.contains('name', 'storage'),
            ws.contains('name', 'post'),
            ws.equals('unit', 'kilowatt hour'),
        ]

        gas_CCS = [
            ws.contains('name', 'natural gas'),
            ws.either(ws.contains('name', 'post'),ws.contains('name', 'pre')),
            ws.contains('name', 'storage'),
            ws.equals('unit', 'kilowatt hour'),
        ]

        biomass_IGCC_CCS = [
            ws.either(ws.contains('name', 'SNG'), ws.contains('name', 'wood'),
                      ws.contains('name', 'BIGCC')),
            ws.contains('name', 'storage'),
            ws.equals('unit', 'kilowatt hour'),
        ]

        biomass_IGCC = [
            ws.contains('name', 'BIGCC'),
            ws.contains('name', 'no CCS'),
            ws.equals('unit', 'kilowatt hour'),
        ]


        return {

            'Coal IGCC': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': coal_IGCC,
                'fuel filters': [ws.either(ws.contains('name', 'Hard coal'),
                                 ws.contains('name', 'Lignite')),
                                 ws.equals('unit', 'megajoule')],
                'technosphere excludes': []
            },

            'Coal IGCC CCS': {
                 'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': coal_IGCC_CCS,
                'fuel filters': [ws.either(ws.contains('name', 'Hard coal'),
                                 ws.contains('name', 'Lignite')),
                                 ws.equals('unit', 'megajoule')],
                'technosphere excludes': []
            },

            'Coal PC': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': filters.coal_electricity + generic_excludes,
                'fuel filters': [ws.either(ws.contains('name', 'hard coal'), ws.contains('name', 'lignite')),
                                ws.doesnt_contain_any('name', ('ash','SOx')),
                                ws.equals('unit', 'kilogram')],
                'technosphere excludes': [],
            },

            'Coal PC CCS':{
                 'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': coal_PC_CCS,
                'fuel filters': [ws.either(ws.contains('name', 'Hard coal'),
                                 ws.contains('name', 'Lignite')),
                                 ws.equals('unit', 'megajoule')],
                'technosphere excludes': []
            },

            'Coal CHP': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': filters.coal_chp_electricity + generic_excludes,
                'fuel filters': [ws.either(ws.contains('name', 'hard coal'), ws.contains('name', 'lignite')),
                                ws.doesnt_contain_any('name', ('ash','SOx')),
                                ws.equals('unit', 'kilogram')],
                'technosphere excludes': [],
            },
            'Gas OC': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': gas_open_cycle_electricity + generic_excludes + no_imports,
                'fuel filters': [ws.either(ws.contains('name', 'natural gas, low pressure'),
                                           ws.contains('name', 'natural gas, high pressure')),
                                ws.equals('unit', 'cubic meter')],
                'technosphere excludes': [],
            },
            'Gas CC': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': filters.gas_combined_cycle_electricity + generic_excludes + no_imports,
                'fuel filters': [ws.either(ws.contains('name', 'natural gas, low pressure'),
                                           ws.contains('name', 'natural gas, high pressure')),
                                ws.equals('unit', 'cubic meter')],
                'technosphere excludes': [],
            },
            'Gas CHP': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': filters.gas_chp_electricity + generic_excludes + no_imports,
                'fuel filters': [ws.either(ws.contains('name', 'natural gas, low pressure'),
                                           ws.contains('name', 'natural gas, high pressure')),
                                ws.equals('unit', 'cubic meter')],
                'technosphere excludes': [],
            },

            'Gas CCS':{
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': gas_CCS,
                'fuel filters': [ws.contains('name', 'Natural gas'),
                                 ws.equals('unit', 'megajoule')],
                'technosphere excludes': []},

            'Oil': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': (filters.oil_open_cycle_electricity
                                       + generic_excludes
                                       + [ws.exclude(ws.contains('name', 'nuclear'))]),
                'fuel filters': [ws.contains('name', 'heavy fuel oil'),
                                    ws.equals('unit', 'kilogram')],
                'technosphere excludes': [],
            },
            'Biomass CHP': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': biomass_chp_electricity + generic_excludes,
                'fuel filters': [ws.either(ws.contains('name', 'wood pellet'),ws.contains('name', 'biogas')),
                                    ws.either(ws.equals('unit', 'kilogram'),ws.equals('unit', 'cubic meter') )],
                'technosphere excludes': [],
            },
            'Biomass IGCC CCS': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': biomass_IGCC_CCS,
                'fuel filters': [ws.either(ws.contains('name', '100% SNG, burned in CC plant'),
                                           ws.contains('name', 'Wood chips'),
                                           ws.contains('name', 'Hydrogen')),
                                 ws.equals('unit', 'megajoule')],
                'technosphere excludes': []
            },
            'Biomass IGCC': {
                'eff_func': self.find_fuel_efficiency_scaling_factor,
                'technology filters': biomass_IGCC,
                'fuel filters': [ws.contains('name', 'Hydrogen'),
                                 ws.equals('unit', 'megajoule')],
                'technosphere excludes': []
            }
        }

    def update_electricity_efficiency(self):
        """
        This method modifies each ecoinvent coal, gas,
        oil and biomass dataset using data from the REMIND model.
        Return a wurst database with modified datasets.

        :return: a wurst database, with rescaled electricity-producing datasets.
        :rtype: list
        """

        technologies_map = self.get_remind_mapping()
        for remind_technology in technologies_map:
            dict_technology = technologies_map[remind_technology]
            print('Rescale inventories and emissions for', remind_technology)

            for ds in ws.get_many(self.db, *dict_technology['technology filters']):
                # Modify using remind efficiency values:
                scaling_factor = dict_technology['eff_func'](ds, dict_technology['fuel filters'], remind_technology)
                self.update_ecoinvent_efficiency_parameter(ds, scaling_factor)

                # Rescale all the technosphere exchanges according to REMIND efficiency values
                wurst.change_exchanges_by_constant_factor(ds, float(scaling_factor), dict_technology['technosphere excludes'],
                                                [ws.doesnt_contain_any('name', self.emissions_map)])

                # Update biosphere exchanges according to REMIND emission values
                for exc in ws.biosphere(ds, ws.either(*[ws.contains('name', x) for x in self.emissions_map])):
                    remind_emission_label = self.emissions_map[exc['name']]

                    remind_emission = self.rmd.electricity_emissions.loc[dict(region=self.ecoinvent_to_remind_location(ds['location']),
                                                          pollutant=remind_emission_label,
                                                          sector=self.rmd.electricity_emission_labels[remind_technology])].values
                    if np.isnan(remind_emission):
                        print(remind_emission, remind_emission_label, ds['name'])

                    if exc['amount'] == 0:
                        wurst.rescale_exchange(exc, remind_emission[0] / 1, remove_uncertainty=True)

                    else:
                        wurst.rescale_exchange(exc, remind_emission[0]/exc['amount'])

        return self.db

    def update_electricity_markets(self):
        """
        Delete electricity markets. Create high, medium and low voltage market groups for electricity.
        Link electricity-consuming datasets to newly created market groups for electricity.
        Return a wurst database with modified datasets.

        :return: a wurst database with new market groups for electricity
        :rtype: list
        """
        # We first need to delete 'market for electricity' and 'market group for electricity' datasets
        print('Remove old electricity datasets')
        list_to_remove = ['market group for electricity, high voltage',
                          'market group for electricity, medium voltage',
                          'market group for electricity, low voltage',
                          'market for electricity, high voltage',
                          'market for electricity, medium voltage',
                          'market for electricity, low voltage',
                            'electricity, high voltage, import',
                          'electricity, high voltage, production mix']
        self.db = [i for i in self.db if not any(stop in i['name'] for stop in list_to_remove)]

        # We then need to create high voltage REMIND electricity markets
        print('Create high voltage markets.')
        self.create_new_markets_high_voltage()
        print('Create medium voltage markets.')
        self.create_new_markets_medium_voltage()
        print('Create low voltage markets.')
        self.create_new_markets_low_voltage()


        # Finally, we need to relink all electricity-consuming activities to the new electricity markets
        print('Link activities to new electricity markets.')
        self.relink_activities_to_new_markets()

        return self.db





