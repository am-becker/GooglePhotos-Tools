"""
Albert Ratajczak, 2019
File with initzialization parameters for app local library
and connection service to Googles APIs
"""

# imports from google-api-python-client library
from googleapiclient.discovery import build

# local imports
from locallibrary import LocalLibrary
from auth import Auth


""" Application settings """
APP_NAME = 'caros-196004'


""" Connection to Google APIs """
# File with the OAuth 2.0 information:
CLIENT_SECRETS_FILE = "client_secret.json"
# This access scope grants read-only access:
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
API_SERVICE_NAME = 'photoslibrary'
API_VERSION = 'v1'


def initialize():
    """
    :return: local library and connection service to Google APIs
    """
    # Setting library
    library = LocalLibrary(APP_NAME)
    # Getting authorization and building service
    authorization = Auth(SCOPES, CLIENT_SECRETS_FILE)
    credentials = authorization.get_credentials()
    discovery_doc = "https://photoslibrary.googleapis.com/$discovery/rest?version=v1"
    service = build("photoslibrary", "v1", credentials=credentials, discoveryServiceUrl=discovery_doc)
    return library, service


if __name__ == '__main__':
    pass
