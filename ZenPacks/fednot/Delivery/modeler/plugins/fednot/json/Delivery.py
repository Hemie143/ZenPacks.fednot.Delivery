# stdlib Imports
import json

# Twisted Imports
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenUtils.Utils import monkeypatch


# TODO : CamelCase (check in YAML)
class Delivery(PythonPlugin):
    """
    Doc about this plugin
    """

    requiredProperties = (
        'zSpringBootPort',
        'zSpringBootApplications',
        'zIVGroups',
        'zIVUser',
        'get_SBAApplications'
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties

    queries = [
        ['sba', 'http://{}:{}/{}/sba/applications'],
        # ['health', 'http://{}:{}/{}/management/health'],
        # ['metricsJob', 'http://{}:{}/{}/management/metrics/job'],
        # ['metricsOrder', 'http://{}:{}/{}/management/metrics/order'],
    ]

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: Use Collect function to define whether Delivery is present on server

    @inlineCallbacks
    def collect(self, device, log):
        log.debug('{}: Modeling collect'.format(device.id))

        port = getattr(device, 'zSpringBootPort', None)
        ivGroups = getattr(device, 'zIVGroups', None)
        if not ivGroups:
            log.error("%s: zIVGroups is not defined", device.id)
            returnValue(None)

        ivUser = getattr(device, 'zIVUser', None)
        if not ivUser:
            log.error("%s: zIVUser is not defined", device.id)
            returnValue(None)

        # apps = getattr(device, 'test', None)
        # apps = device.test2
        log.debug('ivGroups: {}'.format(ivGroups))
        log.debug('ivUser: {}'.format(ivUser))

        # load in previous mappings..
        '''
        if callable(device.get_SBAApplications):
            # needed when we are passed a real device, rather than a
            # deviceproxy, during testing
            apps = device.get_SBAApplications()
            log.debug('****Callable')
        else:
            apps = device.get_SBAApplications
            log.debug('****NOT Callable')
        '''
        applications = device.get_SBAApplications

        log.debug('****Property test: {}'.format(applications))

        # applications = getattr(device, 'zSpringBootApplications', [])

        # TODO: fix this later when SBA is setup to list applications from a generic URL
        # Use http://{}:{}/sba/api/applications
        '''
        app_dict = []
        for app in applications:
            app_dict.append('{{"name":"{}"}}'.format(app))

        app_result = (True, ('apps', '[{}]'.format(','.join(app_dict))))
        '''
        app_result = (True, ('apps', json.dumps(applications)))
        log.debug('app_result: {}'.format(app_result))

        ip_address = device.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)

        for app in applications:
            #  {'hostingServer': 'dvb-app-l15.dev.credoc.be',
            #   'mgmtURL': 'http://dvb-app-l15.dev.credoc.be:8105/delivery-service_v1/management',
            #   'healthURL': 'http://dvb-app-l15.dev.credoc.be:8105/delivery-service_v1/management/health',
            #   'id': 'app_Delivery Service_b0acc0ef',
            #   'serviceURL': 'http://dvb-app-l15.dev.credoc.be:8105/delivery-service_v1'}
            # log.debug('app: {}'.format(app))
            log.debug('app.healthURL: **{}**'.format(app['healthURL']))
            d = sem.run(getPage, app['healthURL'],
                        headers={
                            "Accept": "application/json",
                            "iv-groups": ivGroups,
                            "iv-user": ivUser,
                        })
            d.addCallback(self.add_tag, '{}_{}'.format(app['id'], 'health'))
            deferreds.append(d)

            log.debug('app.mgmtURL: **{}**'.format(app['mgmtURL']))
            url = '{}/metrics/job'.format(app['mgmtURL'])
            log.debug('app.url: **{}**'.format(url))
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "iv-groups": ivGroups,
                            "iv-user": ivUser,
                        })
            d.addCallback(self.add_tag, '{}_{}'.format(app['id'], 'metricsJob'))
            deferreds.append(d)

            '''
            for query in self.queries:
                url = query[1].format(ip_address, port, app)
                # TODO: move iv headers in Config Properties
                d = sem.run(getPage, url,
                            headers={
                                "Accept": "application/json",
                                "User-Agent": "Mozilla/3.0Gold",
                                "iv-groups": ivGroups,
                                "iv-user": ivUser,
                            },
                            )
                d.addCallback(self.add_tag, '{}_{}'.format(app, query[0]))
                deferreds.append(d)
            '''

        results = yield DeferredList(deferreds, consumeErrors=True)
        results.append(app_result)
        for success, result in results:
            if not success:
                log.error('{}: {}'.format(device.id, result.getErrorMessage()))

        returnValue(results)

    def process(self, device, results, log):
        """
        Must return one of :
            - None, changes nothing. Good in error cases.
            - A RelationshipMap, for the device to component information
            - An ObjectMap, for the device device information
            - A list of RelationshipMaps and ObjectMaps, both
        """

        self.result_data = {}
        for success, result in results:
            if success:
                if result:
                    content = json.loads(result[1])
                else:
                    content = {}
                self.result_data[result[0]] = content

        apps_data = self.result_data.get('apps', '')
        log.debug('***apps: {}'.format(apps_data))

        app_maps = []
        rm = []
        rm_comp = []
        rm_job = []
        rm_zip = []
        rm_misc = []
        '''
        for app in apps_data:
            om_app = ObjectMap()
            app_name = app.get('name', '')
            om_app.id = self.prepId('app_{}'.format(app_name))
            om_app.title = app_name
            om_app.serviceName = app_name
            app_maps.append(om_app)
            comp_app = 'springBootApplications/{}'.format(om_app.id)

            comp_maps = []
            health_data = self.result_data.get('{}_health'.format(app_name), '')
            if health_data:
                for comp_name, _ in health_data.items():
                    if comp_name == 'status':
                        continue
                    om_comp = ObjectMap()
                    om_comp.id = self.prepId('comp_{}_{}'.format(app_name, comp_name))
                    om_comp.title = comp_name
                    om_comp.serviceName = app_name
                    comp_maps.append(om_comp)

            job_maps = []
            zip_maps = []
            job_data = self.result_data.get('{}_metricsJob'.format(app_name), '')
            if job_data:
                jobs_list = set([d['jobName'] for d in job_data])
                for job in jobs_list:
                    om_job = ObjectMap()
                    om_job.id = self.prepId('job_{}_{}'.format(app_name, job))
                    om_job.title = job
                    om_job.serviceName = app_name
                    job_maps.append(om_job)
                zips_list = set([d['zipName'] for d in job_data])
                for zipn in zips_list:
                    if zipn is None:
                        continue
                    om_zip = ObjectMap()
                    om_zip.id = self.prepId('zip_{}_{}'.format(app_name, zipn))
                    om_zip.title = zipn
                    om_zip.zipName = zipn
                    zip_maps.append(om_zip)

            rm_comp.append(RelationshipMap(relname='springBootComponents',
                                           modname='ZenPacks.fednot.Delivery.SpringBootComponent',
                                           compname=comp_app,
                                           objmaps=comp_maps))
            rm_job.append(RelationshipMap(relname='springBootJobs',
                                          modname='ZenPacks.fednot.Delivery.SpringBootJob',
                                          compname=comp_app,
                                          objmaps=job_maps))
            rm_zip.append(RelationshipMap(relname='springBootZips',
                                          modname='ZenPacks.fednot.Delivery.SpringBootZip',
                                          compname=comp_app,
                                          objmaps=zip_maps))

            om_order = ObjectMap()
            om_order.id = self.prepId('order_{}'.format(app_name))
            om_order.title = app_name
            om_order.serviceName = app_name
            rm_misc.append(RelationshipMap(relname='springBootOrders',
                                           modname='ZenPacks.fednot.Delivery.SpringBootOrder',
                                           compname=comp_app,
                                           objmaps=[om_order]))

            om_jvm = ObjectMap()
            om_jvm.id = self.prepId('jvm_{}'.format(app_name))
            om_jvm.title = app_name
            om_jvm.serviceName = app_name
            rm_misc.append(RelationshipMap(relname='springBootJVMs',
                                           modname='ZenPacks.fednot.Delivery.SpringBootJVM',
                                           compname=comp_app,
                                           objmaps=[om_jvm]))
        
        rm.append(RelationshipMap(relname='springBootApplications',
                                  modname='ZenPacks.fednot.Delivery.SpringBootApplication',
                                  compname='',
                                  objmaps=app_maps))
        '''
        rm.extend(rm_comp)
        rm.extend(rm_job)
        rm.extend(rm_zip)
        rm.extend(rm_misc)

        return rm
