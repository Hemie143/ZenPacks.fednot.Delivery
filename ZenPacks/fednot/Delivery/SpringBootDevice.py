import json

from . import schema

class SpringBootDevice(schema.SpringBootDevice):

    def test2(self):
        return 'return of the monkeypatch'

    def get_SBAApplications(self):
        app_list = []
        for app in self.springBootApplications():
            app_dict = {}
            app_dict['id'] = app.id
            app_dict['title'] = app.title
            app_dict['serviceID'] = app.serviceID
            app_dict['serviceName'] = app.serviceName
            app_dict['mgmtURL'] = app.mgmtURL
            app_dict['healthURL'] = app.healthURL
            app_dict['serviceURL'] = app.serviceURL
            app_dict['hostingServer'] = app.hostingServer
            app_list.append(app_dict)

        return app_list

