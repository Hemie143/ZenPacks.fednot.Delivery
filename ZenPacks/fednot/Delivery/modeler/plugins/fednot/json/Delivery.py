# stdlib Imports
import json

# Twisted Imports
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage, Agent

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenUtils.Utils import monkeypatch


# TODO : CamelCase (check in YAML)
# TODO : cleanup
# TODO : PEP8
class Delivery(PythonPlugin):
    """
    Doc about this plugin
    """

    requiredProperties = (
        'zSpringBootPort',
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

        applications = device.get_SBAApplications
        app_result = (True, ('apps', json.dumps(applications)))

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
            # TODO: drop obsolete getPage
            d = sem.run(getPage, app['healthURL'],
                        headers={
                            "Accept": "application/json",
                            "iv-groups": ivGroups,
                            "iv-user": ivUser,
                        })
            d.addCallback(self.add_tag, '{}_{}'.format(app['id'], 'health'))
            deferreds.append(d)

            url = '{}/metrics/job'.format(app['mgmtURL'])
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "iv-groups": ivGroups,
                            "iv-user": ivUser,
                        })
            d.addCallback(self.add_tag, '{}_{}'.format(app['id'], 'metricsJob'))
            deferreds.append(d)

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

        app_maps = []
        rm = []
        rm_comp = []
        rm_job = []
        rm_zip = []
        rm_misc = []

        for app in apps_data:
            # {u'mgmtURL': u'http://dvb-app-l01.dev.credoc.be:8105/delivery-service_v1/management',
            # u'healthURL': u'http://dvb-app-l01.dev.credoc.be:8105/delivery-service_v1/management/health',
            # u'id': u'app_Delivery Service_9ffe1d3e', u'hostingServer': u'dvb-app-l01.dev.credoc.be'}
            serviceName = app.get('serviceName', '')
            serviceID = app.get('serviceID', '')
            service = '{}_{}'.format(serviceName.lower().replace(' ', '_'), serviceID)
            app_id = app.get('id', '')
            comp_app = 'springBootApplications/{}'.format(app_id)

            comp_maps = []
            health_data = self.result_data.get('{}_health'.format(app_id), '')
            if health_data:
                for comp_name, _ in health_data.items():
                    if comp_name == 'status':
                        continue
                    om_comp = ObjectMap()
                    # TODO: Avoid space in component name
                    om_comp.id = self.prepId('comp_{}_{}'.format(service, comp_name))
                    om_comp.title = '{} ({} on {})'.format(comp_name, serviceName, app.get('hostingServer'))
                    om_comp.applicationID = app_id
                    om_comp.componentLabel = comp_name
                    # om_comp.serviceName = app_id
                    comp_maps.append(om_comp)

            rm_comp.append(RelationshipMap(relname='springBootComponents',
                                           modname='ZenPacks.fednot.Delivery.SpringBootComponent',
                                           compname=comp_app,
                                           objmaps=comp_maps))

            job_maps = []
            zip_maps = []
            job_data = self.result_data.get('{}_metricsJob'.format(app_id), '')
            if job_data:
                jobs_list = set([d['jobName'] for d in job_data])
                for job in jobs_list:
                    om_job = ObjectMap()
                    om_job.id = self.prepId('job_{}_{}'.format(service, job))
                    om_job.title = '{} ({} on {})'.format(job, serviceName, app.get('hostingServer'))
                    # om_job.serviceName = app_id
                    om_job.applicationID = app_id
                    om_job.jobName = job
                    job_maps.append(om_job)
                zips_list = set([d['zipName'] for d in job_data])
                for zipn in zips_list:
                    if zipn is None:
                        continue
                    om_zip = ObjectMap()
                    om_zip.id = self.prepId('zip_{}_{}'.format(service, zipn))
                    om_zip.title = '{} ({})'.format(zipn, app.get('hostingServer'))
                    om_zip.applicationID = app_id
                    om_zip.zipName = zipn
                    zip_maps.append(om_zip)

            rm_job.append(RelationshipMap(relname='springBootJobs',
                                          modname='ZenPacks.fednot.Delivery.SpringBootJob',
                                          compname=comp_app,
                                          objmaps=job_maps))
            rm_zip.append(RelationshipMap(relname='springBootZips',
                                          modname='ZenPacks.fednot.Delivery.SpringBootZip',
                                          compname=comp_app,
                                          objmaps=zip_maps))

            om_order = ObjectMap()
            om_order.id = self.prepId('order_{}'.format(service))
            om_order.title = 'Order ({} on {})'.format(serviceName, app.get('hostingServer'))
            om_order.serviceName = app_id
            rm_misc.append(RelationshipMap(relname='springBootOrders',
                                           modname='ZenPacks.fednot.Delivery.SpringBootOrder',
                                           compname=comp_app,
                                           objmaps=[om_order]))

            om_jvm = ObjectMap()
            om_jvm.id = self.prepId('jvm_{}'.format(service))
            om_jvm.title = 'JVM ({} on {})'.format(serviceName, app.get('hostingServer'))
            om_jvm.serviceName = app_id
            rm_misc.append(RelationshipMap(relname='springBootJVMs',
                                           modname='ZenPacks.fednot.Delivery.SpringBootJVM',
                                           compname=comp_app,
                                           objmaps=[om_jvm]))

        rm.extend(rm_comp)
        rm.extend(rm_job)
        rm.extend(rm_zip)
        rm.extend(rm_misc)

        return rm
