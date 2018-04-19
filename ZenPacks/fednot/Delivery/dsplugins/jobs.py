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


class Jobs(PythonDataSourcePlugin):
    proxy_attributes = (
        'zSpringBootPort',
        'zSpringBootApplications',
    )

    urls = {
        'health': 'http://{}:{}/{}/management/metrics/job',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    # TODO: check config_key broker
    @classmethod
    def config_key(cls, datasource, context):
        log.info('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.serviceName, 'SB_Job'))

        log.info('config_key context: {}'.format(context.serviceName))

        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_Job'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
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
        # log.debug('Success job - result is {}'.format(result))

        data = self.new_data()

        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics

        health_data = ds_data.get('health', '')
        timestamp_now = int(time.time())
        for datasource in config.datasources:
            componentID = prepId(datasource.component)
            service_name = datasource.params['serviceName']
            r = re.match('{}_?(.*)'.format(service_name), componentID)
            component_label = r.group(1)
            log.debug('comp: {}'.format(component_label))
            job_list = [d for d in health_data if d['jobName'] == component_label]
            # log.debug('job_list: {}'.format(job_list))
            for job in job_list:
                rundate = job['runDate']
                datetime_obj = datetime.datetime(rundate['year'], rundate['monthValue'], rundate['dayOfMonth'],
                                                 rundate['hour'], rundate['minute'], rundate['second'])
                job['timestamp'] = int(datetime_obj.strftime('%s'))
            last_job = sorted(job_list, key=itemgetter('timestamp'), reverse=True)[0]
            log.debug('last_job: {}'.format(last_job))
            job_status = last_job['status']
            job_age = timestamp_now - last_job['timestamp']

        # log.debug('Success job - result is {}'.format(len(ds_data)))

        # log.debug('Success job - result is {}'.format(ds_data))

        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
