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
        'zIVGroups',
        'zIVUser',
    )

    urls = {
        'job': '{}/management/metrics/job',
    }

    @staticmethod
    def add_tag(result, label):
        return tuple((label, result))

    def collect(self, config):
        log.debug('Starting Delivery Jobs collect')
        # TODO : switch to twisted.web.client.Agent, getPage is becoming Deprecated
        # http://twisted.readthedocs.io/en/twisted-17.9.0/web/howto/client.html

        ip_address = config.manageIp
        if not ip_address:
            log.error("%s: IP Address cannot be empty", device.id)
            returnValue(None)

        # Gather the info about applications
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
            d = sem.run(getPage, url,
                        headers={
                            "Accept": "application/json",
                            "User-Agent": "Mozilla/3.0Gold",
                            "iv-groups": datasource.zIVGroups,
                            "iv-user": datasource.zIVUser,
                        },
                        )
            tag = '{}_{}'.format(datasource.datasource, applicationNameID)
            d.addCallback(self.add_tag, tag)
            deferreds.append(d)
        return DeferredList(deferreds)

class Jobs(MetricsJob):

    @classmethod
    def config_key(cls, datasource, context):
        log.debug('In config_key {} {} {} {}'.format(context.device().id, datasource.getCycleTime(context),
                                                    context.applicationNameID, 'SB_Job'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.applicationNameID,
            'SB_Job'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
        params = {}
        params['hostingServer'] = context.hostingServer
        params['serviceURL'] = context.serviceURL
        params['applicationName'] = context.applicationName
        params['applicationNameID'] = context.applicationNameID
        params['jobName'] = context.jobName
        log.debug('params is {}'.format(params))
        return params

    def onSuccess(self, result, config):
        log.debug('Success job - result is {}'.format(result))
        # TODO : cleanup job onSuccess

        status_maps = {'DONE': [0, 'Job {} ({} on {}) is OK with zip: {}'],
                       'ERROR': [5, 'Job {} ({} on {}) is in error with zip: {}']
                       }

        data = self.new_data()

        ds_data = {}
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics



        # TODO: Check data content
        # TODO: Model new jobs
        timestamp_now = calendar.timegm(time.gmtime())
        for datasource in config.datasources:
            componentID = prepId(datasource.component)
            hostingServer = datasource.params['hostingServer']
            applicationName = datasource.params['applicationName']
            applicationNameID = datasource.params['applicationNameID']
            jobName = datasource.params['jobName']
            tag = '{}_{}'.format(datasource.datasource, applicationNameID)
            jobs_data = ds_data.get(tag, '')
            job_list = [d for d in jobs_data if d['jobName'] == jobName]
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
            job_status_map = status_maps.get(job_status, [3, 'Job {} ({} on {}) has an unknown issue'])
            data['values'][componentID]['status'] = job_status_map[0]
            zip_name = last_job['zipName']
            msg = job_status_map[1].format(jobName, applicationName, hostingServer, zip_name)
            data['events'].append({
                'device': config.id,
                'component': componentID,
                'severity': job_status_map[0],
                'eventKey': 'JobHealth',
                'summary': msg,
                'message': msg,
                'eventClass': '/Status/App/Delivery/Job',
                'zipName': zip_name
            })
            data['values'][componentID]['age'] = job_age
            data['values'][componentID]['dataCount'] = last_job['dataCount']
            data['values'][componentID]['missingCount'] = last_job['missingCount']

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
                                                    context.applicationNameID, 'SB_Zip'))
        return (
            context.device().id,
            datasource.getCycleTime(context),
            context.applicationNameID,
            'SB_Zip'
        )

    @classmethod
    def params(cls, datasource, context):
        log.debug('Starting Delivery Jobs params')
        params = {}
        params['hostingServer'] = context.hostingServer
        params['serviceURL'] = context.serviceURL
        params['applicationName'] = context.applicationName
        params['applicationNameID'] = context.applicationNameID
        params['applicationComponentID'] = context.applicationComponentID
        params['zipName'] = context.zipName
        log.debug('params is {}'.format(params))
        return params

    def onSuccess(self, result, config):
        """ This one is running once per application"""
        log.debug('Success job - result is {}'.format(result))
        data = self.new_data()
        ds_data = {}
        count = 0
        for success, ddata in result:
            if success:
                ds = ddata[0]
                metrics = json.loads(ddata[1])
                ds_data[ds] = metrics
                count += 1

        ds0 = config.datasources[0]
        applicationName = ds0.params['applicationName']                                     # Delivery Service
        applicationNameID = ds0.params['applicationNameID']
        tag = '{}_{}'.format(ds0.datasource, applicationNameID)
        hostingServer = ds0.params['hostingServer']
        zips_data = ds_data.get(tag, '')
        all_zips_list = list(set([d['zipName'] for d in zips_data if d['zipName']]))

        # TODO: Analyze whether it should run per component or per content of ds_data
        # ds_data contains a single entry with a tag that should match the applicationNameID
        # The vars computed at the beginning of the loop are unique per application, not per component
        for datasource in config.datasources:
            # Runs once per zipfile modeled before
            componentID = prepId(datasource.component)
            zipName = datasource.params['zipName']
            zip_list = [d for d in zips_data if d['zipName'] == zipName]
            for zip in zip_list:
                rundate = zip['runDate']
                # UTC
                # Don't use datetime.datetime because it takes into account the TZ
                # datetime_obj = datetime.datetime(rundate['year'], rundate['monthValue'], rundate['dayOfMonth'],
                #                                        rundate['hour'], rundate['minute'], rundate['second'])

                time_zip = '{}/{:02d}/{:02d} {:02d}:{:02d}:{:02d}'.format(rundate['year'], rundate['monthValue'],
                                                                          rundate['dayOfMonth'],
                                                                          rundate['hour'],
                                                                          rundate['minute'],
                                                                          rundate['second'])
                timestring_zip = time.strptime(time_zip, '%Y/%m/%d %H:%M:%S')
                zip['timestamp'] = calendar.timegm(timestring_zip)
            zip_list = sorted(zip_list, key=itemgetter('timestamp'), reverse=True)
            if zip_list == []:          # Component has no entry in JSON output
                data['values'][componentID]['dataCount'] = 0
                data['values'][componentID]['missingCount'] = 0
                msg = 'Zip {} ({} on {}) has been removed'.format(componentID, applicationName, hostingServer)
                data['events'].append({
                    'device': config.id,
                    'component': componentID,
                    'severity': 2,
                    'eventKey': 'ZipHealth',
                    'eventClassKey': 'ZipHealth',
                    'summary': msg,
                    'message': msg,
                    'eventClass': '/Status/App',
                })
                continue

            # TODO: Remove the following unless required to compute age
            last_zip = zip_list[0]
            # Use full set of data for given zipfile
            dataCountSet = set([x['dataCount'] for x in zip_list])
            missingCountSet = set([x['missingCount'] for x in zip_list])

            # If dataCountSet has more than one entry, it means that for the zipfile, some data has been lost
            # If any value in missingCountSet is different from zero, some data has been lost
            if len(dataCountSet) > 1 or not(0 in missingCountSet):
                sev = 4
                msg = 'Zip {} ({} on {}) has lost messages'.format(componentID, applicationName, hostingServer)
            else:
                sev = 0
                msg = 'Zip {} ({} on {}) is OK'.format(componentID, applicationName, hostingServer)

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
            # end of loop for a single zipfile

        # Model zipfiles
        zip_maps = []
        for zipn in all_zips_list:
            if zipn is None:
                continue
            om_zip = ObjectMap()
            om_zip.id = prepId('zip_{}_{}'.format(applicationNameID, zipn))
            om_zip.title = '{} ({} on {})'.format(zipn, applicationName, hostingServer)
            om_zip.applicationName = applicationName
            om_zip.zipName = zipn
            zip_maps.append(om_zip)

        applicationComponentID = ds0.params['applicationComponentID']
        comp_app = 'springBootApplications/{}'.format(applicationComponentID)
        data['maps'].append(RelationshipMap(relname='springBootZips',
                                      modname='ZenPacks.fednot.Delivery.SpringBootZip',
                                      compname=comp_app,
                                      objmaps=zip_maps))

        log.debug('Success job - data is {}'.format(data))
        return data

    def onError(self, result, config):
        log.error('Error - result is {}'.format(result))
        # TODO: send event of collection failure
        return {}
