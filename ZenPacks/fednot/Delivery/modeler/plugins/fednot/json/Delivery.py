# stdlib Imports
import json

# Twisted Imports
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap


# TODO : CamelCase (check in YAML)
class Delivery(PythonPlugin):
    """
    Doc about this plugin
    """

    requiredProperties = (
        'zSpringBootPort',
        'zSpringBootApplications',
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties

    queries = [
        ['health', 'http://{}:{}/{}/health'],
        ['metricsJob', 'http://{}:{}/{}/metrics/job'],
        ['metricsOrder', 'http://{}:{}/{}/metrics/order'],
    ]

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @inlineCallbacks
    def collect(self, device, log):
        log.debug('{}: Modeling collect'.format(device.id))

        port = getattr(device, 'zSpringBootPort', None)
        applications = getattr(device, 'zSpringBootApplications', [])

        # TODO: fix this later when SBA is setup to list applications from a generic URL
        app_dict = []
        for app in applications:
            app_dict.append('{{"name":"{}"}}'.format(app))

        app_result = (True, ('apps', '[{}]'.format(','.join(app_dict))))

        ip_address = device.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)

        for app in applications:
            for query in self.queries:
                url = query[1].format(ip_address, port, app)
                d = sem.run(getPage, url,
                            headers={
                                "Accept": "application/json",
                                "User-Agent": "Mozilla/3.0Gold",
                            },
                            )
                d.addCallback(self.add_tag, '{}_{}'.format(app, query[0]))
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
        rm_misc = []
        for app in apps_data:
            om_app = ObjectMap()
            app_name = app.get('name', '')
            om_app.id = self.prepId(app_name)
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
                    om_comp.id = self.prepId(comp_name)
                    om_comp.title = comp_name
                    comp_maps.append(om_comp)

            job_maps = []
            job_data = self.result_data.get('{}_metricsJob'.format(app_name), '')
            if job_data:
                jobs_list = set([d['jobName'] for d in job_data])
                for job in jobs_list:
                    om_job = ObjectMap()
                    om_job.id = self.prepId(job)
                    om_job.title = job
                    job_maps.append(om_job)

            rm_comp.append(RelationshipMap(relname='springBootComponents',
                                           modname='ZenPacks.fednot.Delivery.SpringBootComponent',
                                           compname=comp_app,
                                           objmaps=comp_maps))
            rm_job.append(RelationshipMap(relname='springBootJobs',
                                          modname='ZenPacks.fednot.Delivery.SpringBootJob',
                                          compname=comp_app,
                                          objmaps=job_maps))

            om_order = ObjectMap()
            om_order.id = self.prepId(app_name)
            om_order.title = app_name
            rm_misc.append(RelationshipMap(relname='springBootOrders',
                                           modname='ZenPacks.fednot.Delivery.SpringBootOrder',
                                           compname=comp_app,
                                           objmaps=[om_order]))

            om_jvm = ObjectMap()
            om_jvm.id = self.prepId(app_name)
            om_jvm.title = app_name
            rm_misc.append(RelationshipMap(relname='springBootJVMs',
                                           modname='ZenPacks.fednot.Delivery.SpringBootJVM',
                                           compname=comp_app,
                                           objmaps=[om_jvm]))

        rm.append(RelationshipMap(relname='springBootApplications',
                                  modname='ZenPacks.fednot.Delivery.SpringBootApplication',
                                  compname='',
                                  objmaps=app_maps))
        rm.extend(rm_comp)
        rm.extend(rm_job)
        rm.extend(rm_misc)

        return rm