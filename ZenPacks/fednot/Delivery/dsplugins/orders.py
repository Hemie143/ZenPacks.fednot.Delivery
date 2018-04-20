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
log = logging.getLogger('zen.PythonDeliveryJobs')


class Orders(PythonDataSourcePlugin):
    proxy_attributes = (
        'zSpringBootPort',
        'zSpringBootApplications',
    )

    urls = {
        'order': 'http://{}:{}/{}/management/metrics/order',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.serviceName, 'SB_Job'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_Order'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
        params = {'serviceName': context.serviceName}
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting Delivery orders collect')
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

        data = self.new_data()
        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics

        orders_data = ds_data.get('order', '')
        log.debug('Success orders - orders_data is {}'.format(orders_data))
        ds0 = config.datasources[0]
        componentID = prepId(ds0.component)
        log.debug('componentID: {}'.format(componentID))
        log.debug('points: {}'.format(ds0.points))
        for point in ds0.points:
            log.debug('point: {}'.format(point.id))
        total_check = 0
        for order in orders_data:
            order_status = str(order['status'])
            order_value = order['count']
            data['values'][componentID][order_status.lower()] = order_value
            if order_status != 'TOTAL':
                total_check += order_value
        data['values'][componentID]['total_check'] = total_check

        # log.debug('Success job - result is {}'.format(len(ds_data)))

        log.debug('Success job - data is {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
