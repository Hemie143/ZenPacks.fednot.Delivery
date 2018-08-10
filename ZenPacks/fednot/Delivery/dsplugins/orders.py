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
log = logging.getLogger('zen.PythonDeliveryOrders')


class Orders(PythonDataSourcePlugin):
    proxy_attributes = (
        'zSpringBootPort',
        'zIVGroups',
        'zIVUser',
    )

    urls = {
        'order': '{}/management/metrics/order',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.applicationName, 'SB_Job'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'SB_Order'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
        params = {}
        params['serviceURL'] = context.serviceURL
        params['applicationNameID'] = context.applicationNameID
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting Delivery orders collect')
        # TODO : cleanup job collect

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        applicationList = []
        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            applicationNameID = datasource.params['applicationNameID']
            if applicationNameID in applicationList:
                continue
            applicationList.append(applicationNameID)
            serviceURL = datasource.params['serviceURL']
            url = self.urls[datasource.datasource].format(serviceURL)
            # TODO : move headers to Config properties
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "Mozilla/3.0Gold",
                            "iv-groups": datasource.zIVGroups,
                            "iv-user": datasource.zIVUser,
                        },
                        )
            tag = '{}_{}'.format(datasource.datasource, applicationNameID)      # order_app_delivery_service_3db30547
            d.addCallback(self.add_tag, tag)
            deferreds.append(d)
        return DeferredList(deferreds)

    def onSuccess(self, result, config):
        log.debug('Success job - result is {}'.format(result))
        # TODO : cleanup job onSuccess
        data = self.new_data()
        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics

        ds0 = config.datasources[0]
        componentID = prepId(ds0.component)
        applicationNameID = ds0.params['applicationNameID']
        tag = '{}_{}'.format(ds0.datasource, applicationNameID)
        orders_data = ds_data.get(tag, '')

        total_check = 0
        total_metrics = 0
        for order in orders_data:
            order_status = str(order['status'])
            order_value = order['count']
            data['values'][componentID][order_status.lower()] = order_value
            if order_status != 'TOTAL':
                total_check += order_value
            else:
                total_metrics = order_value
        data['values'][componentID]['total_check'] = total_metrics - total_check

        log.debug('Success job - data is {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
