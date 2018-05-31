# stdlib Imports
import json
import logging
import re
import datetime
import time
import calendar
# import base64
from operator import itemgetter

# Twisted Imports
from twisted.internet.defer import returnValue, DeferredSemaphore, DeferredList, inlineCallbacks
from twisted.web.client import getPage

# Zenoss imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin
from Products.ZenUtils.Utils import prepId
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap


# Setup logging
log = logging.getLogger('zen.PythonDeliveryJobs')


class MetricsJob(PythonDataSourcePlugin):
    proxy_attributes = (
        'zSpringBootPort',
        'zSpringBootApplications',
    )

    urls = {
        'job': 'http://{}:{}/{}/management/metrics/job',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
        params = {'serviceName': context.serviceName}
        log.debug('params is {}'.format(params))
        return params

    def collect(self, config):
        log.debug('Starting Delivery health collect')
        # TODO : cleanup job collect
        # TODO : switch to twisted.web.client.Agent, getPage is becoming Deprecated
        # http://twisted.readthedocs.io/en/twisted-17.9.0/web/howto/client.html

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        deferreds = []
        sem = DeferredSemaphore(1)
        for datasource in config.datasources:
            service_name = datasource.params['serviceName']
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


class Jobs(MetricsJob):

    # TODO: check config_key
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.serviceName, 'SB_Job'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_Job'
        )

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

        jobs_data = ds_data.get('job', '')
        # TODO: Check data content
        # timestamp_now = int(time.gmtime())    # UTC
        timestamp_now = calendar.timegm(time.gmtime())
        # log.debug('timestamp_now: {}'.format(timestamp_now))
        for datasource in config.datasources:
            componentID = prepId(datasource.component)
            # log.debug('componentID: {}'.format(componentID))
            service_name = datasource.params['serviceName']
            r = re.match('job_{}_?(.*)'.format(service_name), componentID)
            component_label = r.group(1)
            job_list = [d for d in jobs_data if d['jobName'] == component_label]
            for job in job_list:
                rundate = job['runDate']
                # UTC
                # Don't use datetime.datetime because it takes into account the TZ
                # datetime_obj = datetime.datetime(rundate['year'], rundate['monthValue'], rundate['dayOfMonth'],
                #                                        rundate['hour'], rundate['minute'], rundate['second'])

                time_job = '{}/{:02d}/{:02d} {:02d}:{:02d}:{:02d}'.format(rundate['year'], rundate['monthValue'],
                                                                          rundate['dayOfMonth'],
                                                                          rundate['hour'],
                                                                          rundate['minute'],
                                                                          rundate['second'])
                timestring_job = time.strptime(time_job, '%Y/%m/%d %H:%M:%S')
                job['timestamp'] = calendar.timegm(timestring_job)
            # TODO: Check that job_list isn't empty
            last_job = sorted(job_list, key=itemgetter('timestamp'), reverse=True)[0]
            job_status = last_job['status']
            job_age = (float(timestamp_now) - float(last_job['timestamp'])) / 60.0
            job_status_map = status_maps.get(job_status, [3, 'Job {} has an unknown issue'])
            data['values'][componentID]['status'] = job_status_map[0]
            data['events'].append({
                'device': config.id,
                'component': componentID,
                'severity': job_status_map[0],
                'eventKey': 'JobHealth',
                'eventClassKey': 'JobHealth',
                'summary': job_status_map[1].format(componentID),
                'message': job_status_map[1].format(componentID),
                'eventClass': '/Status/App',
                'zipName': last_job['zipName']
            })
            data['values'][componentID]['age'] = job_age
            data['values'][componentID]['dataCount'] = last_job['dataCount']
            data['values'][componentID]['missingCount'] = last_job['missingCount']

        # log.debug('Success job - result is {}'.format(len(ds_data)))

        log.debug('Success job - data is {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}


class Zips(MetricsJob):

    # TODO: check config_key
    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.serviceName, 'SB_Job'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.serviceName,
            'SB_Zip'
        )

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

        jobs_data = ds_data.get('job', '')

        all_zips_list = list(set([d['zipName'] for d in jobs_data if d['zipName']]))
        log.debug('all_zips_list 1: {}'.format(all_zips_list))
        service_name = ''

        for datasource in config.datasources:
            componentID = prepId(datasource.component)
            service_name = datasource.params['serviceName']
            r = re.match('zip_{}_?(.*)'.format(service_name), componentID)
            component_label = r.group(1)
            zip_list = [d for d in jobs_data if d['zipName'] == component_label]
            if component_label in all_zips_list:
                all_zips_list.remove(component_label)
            log.debug('zip_list: {}'.format(zip_list))
            if zip_list == []:
                log.debug('zip_list is EMPTY')
                data['values'][componentID]['dataCount'] = 0
                data['values'][componentID]['missingCount'] = 0
                data['events'].append({
                    'device': config.id,
                    'component': componentID,
                    'severity': 2,
                    'eventKey': 'ZipHealth',
                    'eventClassKey': 'ZipHealth',
                    'summary': 'Zip {} has been removed'.format(component_label),
                    'message': 'Zip {} has been removed'.format(component_label),
                    'eventClass': '/Status/App',
                })
                continue

            dataCountSet = set([x['dataCount'] for x in zip_list])
            missingCountSet = set([x['missingCount'] for x in zip_list])

            if len(dataCountSet) > 1 or len(missingCountSet) > 1:
                sev = 4
                msg = 'Zip {} has lost messages'.format(component_label)
            else:
                sev = 0
                msg = 'Zip {} is OK'.format(component_label)

            data['values'][componentID]['zip_status'] = sev
            data['values'][componentID]['dataCount'] = max(dataCountSet)
            data['values'][componentID]['missingCount'] = max(missingCountSet)
            data['events'].append({
                'device': config.id,
                'component': componentID,
                'severity': sev,
                'eventKey': 'ZipHealth',
                'eventClassKey': 'ZipHealth',
                'summary': msg,
                'message': msg,
                'eventClass': '/Status/App',
            })

        zip_maps = []
        for zipn in all_zips_list:
            if zipn is None:
                continue
            om_zip = ObjectMap()
            # om_zip.id = self.prepId('{}_{}'.format(service_name, zipn))
            om_zip.id = prepId('{}_{}'.format(service_name, zipn))
            om_zip.title = zipn
            om_zip.zipName = zipn
            zip_maps.append(om_zip)

        '''
                    rm_zip.append(RelationshipMap(relname='springBootZips',
                                          modname='ZenPacks.fednot.Delivery.SpringBootZip',
                                          compname=comp_app,
                                          objmaps=zip_maps))

        '''
        '''
        data['maps'].append(
            ObjectMap({
                'relname' : 'dirs',
                'modname': 'ZenPacks.community.DirFile.Dir',
                'id': ds.component,
                'bytesUsed': v,
                }))
        '''

        if all_zips_list:
            log.debug('all_zips_list is not empty')
            log.debug('all_zips_list: {}'.format(len(all_zips_list)))

        log.debug('zip_maps: {}'.format(zip_maps))
        log.debug('all_zips_list 0: {}'.format(all_zips_list))
        log.debug('Success job - data is {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
