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
    )

    urls = {
        'health': 'http://{}:{}/{}/management/health',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.info('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                     context.serviceName, 'SB_health'))

        # log.info('config_key datasource: {}'.format(datasource.__dict__))
        # log.info('config_key context: {}'.format(context.__dict__))

        log.info('config_key context: {}'.format(context.serviceName))

        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_health'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery health params')
        params = {'serviceName': context.serviceName}
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting Delivery health collect')

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            service_name = datasource.params['serviceName']
            log.debug('collect datasource: {}'.format(datasource.datasource))
            log.debug('collect component: {}'.format(datasource.component))
            url = self.urls[datasource.datasource].format(ip_address, datasource.zSpringBootPort, service_name)
            log.debug('collect URL: {}'.format(url))
            # basic_auth = base64.encodestring('{}:{}'.format(datasource.zJolokiaUsername, datasource.zJolokiaPassword))
            # auth_header = "Basic " + basic_auth.strip()
            # TODO : move headers to Config properties
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "Mozilla/3.0Gold",
                            "iv-groups": "GRP_MANAGEMENT",
                            "iv-user": "cs_monitoring",
                        },
                        )
            d.addCallback(self.add_tag, datasource.datasource)
            deferreds.append(d)
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('Success - result is {}'.format(result))

        data = self.new_data()

        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics

        health_data = ds_data.get('health', '')
        if health_data:
            for datasource in config.datasources:
                componentID = prepId(datasource.component)
                service_name = datasource.params['serviceName']
                if componentID == service_name:
                    component_label = service_name
                    health = health_data.get('status', '')
                else:
                    r = re.match('{}_?(.*)'.format(service_name), componentID)
                    component_label = r.group(1)
                    health = health_data.get(component_label, '')
                    if health:
                        health = health.get('status')
                if health.upper() == "UP":
                    data['values'][componentID]['status'] = 0
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
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
