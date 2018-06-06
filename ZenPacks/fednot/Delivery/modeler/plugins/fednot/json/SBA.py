# stdlib Imports
import json
import re

# Twisted Imports
from twisted.internet.defer import inlineCallbacks, returnValue, DeferredSemaphore, DeferredList
from twisted.web.client import getPage

# Zenoss Imports
from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap


# TODO : CamelCase (check in YAML)
class SBA(PythonPlugin):
    """
    Doc about this plugin
    """

    requiredProperties = (
        'zSpringBootPort',
        'zSpringBootApplications',
        'zIVGroups',
        'zIVUser',
    )

    deviceProperties = PythonPlugin.deviceProperties + requiredProperties

    queries = [
        ['sba', 'http://{}:{}/sba/api/applications'],
    ]

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @inlineCallbacks
    def collect(self, device, log):
        log.debug('{}: Modeling collect'.format(device.id))

        port = getattr(device, 'zSpringBootPort', None)
        ivGroups = getattr(device, 'zIVGroups', None)
        ivUser = getattr(device, 'zIVUser', None)

        ip_address = device.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)

        for query in self.queries:
            url = query[1].format(ip_address, port)
            # TODO: move iv headers in Config Properties
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "Mozilla/3.0Gold",
                            "iv-groups": ivGroups,
                            "iv-user": ivUser,
                        },
                        )
            d.addCallback(self.add_tag, '{}'.format(query[0]))
            deferreds.append(d)

        results = yield DeferredList(deferreds, consumeErrors=True)
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

        sba_data = self.result_data.get('sba', '')

        log.debug('sba_data: {}'.format(len(sba_data)))

        app_maps = []
        rm = []
        for app in sba_data:
            om_app = ObjectMap()
            app_name = app.get('name', '')
            app_id = app.get('id', '')
            om_app.id = self.prepId('app_{}_{}'.format(app_name, app_id))
            om_app.serviceName = app_name
            mgmtURL = app.get('managementUrl', '')
            om_app.mgmtURL = mgmtURL
            om_app.healthURL = app.get('healthUrl', '')
            om_app.serviceURL = app.get('serviceUrl', '')
            r = re.match(r'^(.*:)//([A-Za-z0-9\-\.]+)(:[0-9]+)?(.*)$', mgmtURL)
            server = r.group(2)
            om_app.hostingServer = server
            om_app.title = '{} on {} ({})'.format(app_name, server, app_id)

            app_maps.append(om_app)
            # comp_app = 'springBootApplications/{}'.format(om_app.id)

        rm.append(RelationshipMap(relname='springBootApplications',
                                  modname='ZenPacks.fednot.Delivery.SpringBootApplication',
                                  compname='',
                                  objmaps=app_maps))


        return rm
