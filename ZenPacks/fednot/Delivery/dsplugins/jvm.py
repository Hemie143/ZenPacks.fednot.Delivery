# stdlib Imports
import json
import logging
import re
import datetime
import time
import base64
from operator import itemgetter

# Twisted Imports
from twisted.internet.defer import returnValue, DeferredSemaphore, DeferredList, inlineCallbacks
from twisted.web.client import getPage

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin
from Products.ZenUtils.Utils import prepId

# Setup logging
log = logging.getLogger('zen.PythonDeliveryJVM')


class JVM(PythonDataSourcePlugin):
    proxy_attributes = (
        'zSpringBootPort',
        'zSpringBootApplications',
    )

    urls = {
        'jvm': 'http://{}:{}/{}/management/metrics',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.serviceName, 'SB_JVM'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_JVM'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
        params = {'serviceName': context.serviceName}
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting Delivery health collect')
        # TODO : cleanup job collect

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            service_name = datasource.params['serviceName']
            # log.debug('collect datasource: {}'.format(datasource.datasource))
            # log.debug('collect component: {}'.format(datasource.component))
            url = self.urls[datasource.datasource].format(ip_address, datasource.zSpringBootPort, service_name)
            # log.debug('collect URL: {}'.format(url))
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
        # log.debug('Success job - result is {}'.format(result))
        # TODO : cleanup job onSuccess

        status_maps = {'DONE': [0, 'Job {} is OK'],
                       'ERROR': [5, 'Job {} is in error']
                       }

        data = self.new_data()

        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics

        jvm_data = ds_data.get('jvm', '')
        log.debug('jvm_data: {}'.format(jvm_data))
        if not jvm_data:
            # TODO: Add event: no data collected
            return data
        ds0 = config.datasources[0]
        componentID = prepId(ds0.component)
        for point in ds0.points:
            log.debug('point: {}'.format(point.id))
            if point.id in jvm_data:
                data['values'][componentID][point.id] = jvm_data[point.id]


        mem_used = jvm_data['mem'] - jvm_data['mem.free']
        data['values'][componentID]['mem.used'] = mem_used
        data['values'][componentID]['mem.used_percentage'] = float(mem_used) / float(jvm_data['mem']) * 100.0
        data['values'][componentID]['heap.used_percentage'] = float(jvm_data['heap.used']) / float(jvm_data['heap']) \
                                                              * 100.0
        log.debug('Success job - data is {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
