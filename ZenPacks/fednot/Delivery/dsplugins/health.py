# stdlib Imports
import json
import logging
import re
import base64

# Twisted Imports
from twisted.internet.defer import returnValue, DeferredSemaphore, DeferredList, inlineCallbacks
from twisted.web.client import getPage

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin
from Products.ZenUtils.Utils import prepId

# Setup logging
log = logging.getLogger('zen.PythonDeliveryHealth')


class Health(PythonDataSourcePlugin):

    proxy_attributes = (
        'zSpringBootPort',
        'zSpringBootApplications',
        'zIVGroups',
        'zIVUser',
    )

    urls = {
        # 'health': 'http://{}:{}/{}/management/health',
        'health': '{}/management/health',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                     context.serviceName, 'SB_health'))

        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_health'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery health params')
        params = {}
        params['hostingServer'] = context.hostingServer
        params['serviceURL'] = context.serviceURL
        params['applicationID'] = context.applicationID
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('AAA Starting Delivery health collect')
        # log.debug('AAA config: {}'.format(config.__dict__))
        # Runs once at Application level and once more at components level
        # TODO: test without plugin_classname for components in YAML

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        # Gather the info about services
        serviceList = []
        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            log.debug('AAA datasource: {}'.format(datasource.__dict__))
            # log.debug('AAA datasource: {}'.format(datasource.__primary_parent__))
            applicationID = datasource.params['applicationID']
            if applicationID in serviceList:
                continue
            log.debug('AAA not skipping')
            # serviceList[applicationID] = dict()
            serviceList.append(applicationID)
            serviceURL = datasource.params['serviceURL']
            url = self.urls[datasource.datasource].format(serviceURL)
            log.debug('AAA collect URL: {}'.format(url))
            # basic_auth = base64.encodestring('{}:{}'.format(datasource.zJolokiaUsername, datasource.zJolokiaPassword))
            # auth_header = "Basic " + basic_auth.strip()
            # TODO : move headers to Config properties
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "Mozilla/3.0Gold",
                            "iv-groups": datasource.zIVGroups,
                            "iv-user": datasource.zIVUser,
                        },
                        )
            tag = '{}_{}'.format(datasource.datasource, applicationID)
            # d.addCallback(self.add_tag, datasource.datasource)
            d.addCallback(self.add_tag, tag)
            deferreds.append(d)
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('BBB Success - result is {}'.format(result))

        data = self.new_data()

        ds_data = {}
        for success, ddata in result:
            # If not success ?
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics
            else:
                log.debug('Health collect - result :'.format(result))

        log.debug('BBB ds_data {}'.format(ds_data))

        # health_data = ds_data.get('health', '')
        # TODO: Check content data & create event
        #if health_data:
        for datasource in config.datasources:
            componentID = prepId(datasource.component)          # comp_delivery_service_3db30547_jobs
            # service_name = datasource.params['serviceName']     # app_Delivery Service_3db30547
            applicationID = datasource.params['applicationID']
            log.debug('CCC componentID: {}'.format(componentID))
            log.debug('CCC applicationID: {}'.format(applicationID))
            # log.debug('service_name: {}'.format(service_name))
            tag = '{}_{}'.format(datasource.datasource, applicationID)
            health_data = ds_data.get(tag, '')
            log.debug('CCC health_data: {}'.format(health_data))

            # comp_app = 'app_{}'.format(service_name)
            if componentID == applicationID:
                # Application health
                component_label = 'XXX'
                if health_data:
                    health = health_data.get('status', 'DOWN')
                else:
                    health = "DOWN"
                log.debug('DDD applicationID: {}'.format(applicationID))
                log.debug('DDD health: {}'.format(health))
            else:
                # Application component health
                # r = re.match('comp_{}_?(.*)'.format(service_name), componentID)
                # component_label = r.group(1)
                component_label = 'YYY'
                health = health_data.get(component_label, '')
                if health:
                    health = health.get('status')
            # TODO: Add status OUT_OF_SERVICE & UNKNOWN
            # TODO: Correct eventClass
            if health.upper() == "UP":
                log.debug('EEE componentID: {}'.format(componentID))
                data['values'][componentID]['status'] = 0
                log.debug('EEE data: {}'.format(data))
                data['events'].append({
                    'device': config.id,
                    'component': componentID,
                    'severity': 0,
                    'eventKey': 'SBHealth',
                    'eventClassKey': 'SBHealth',
                    'summary': 'Application {} - Status is Up'.format(component_label),
                    'eventClass': '/Status',
                    })
            elif health.upper() == "DOWN":
                data['values'][componentID]['status'] = 5
                data['events'].append({
                    'device': config.id,
                    'component': componentID,
                    'severity': 5,
                    'eventKey': 'SBHealth',
                    'eventClassKey': 'SBHealth',
                    'summary': 'Application {} - Status is Down'.format(component_label),
                    'eventClass': '/Status',
                    })
            else:
                data['values'][componentID]['status'] = 3
                data['events'].append({
                    'device': config.id,
                    'component': componentID,
                    'severity': 3,
                    'eventKey': 'SBHealth',
                    'eventClassKey': 'SBHealth',
                    'summary': 'Application {} - Status is {}'.format(component_label, health.title()),
                    'eventClass': '/Status',
                    })
            log.debug('FFF data: {}'.format(data['values']))
            log.debug('FFF len: {}'.format(len(data['values'])))
        log.debug('ZZZ data: {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
