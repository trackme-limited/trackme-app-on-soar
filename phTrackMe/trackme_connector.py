#!/usr/bin/python
# -*- coding: utf-8 -*-

# Python 3 Compatibility imports
from __future__ import print_function, unicode_literals

__author__ = "TrackMe Limited"
__copyright__ = "Copyright 2024, TrackMe Limited, U.K."
__credits__ = "TrackMe Limited, U.K."
__license__ = "TrackMe Limited, all rights reserved"
__version__ = "0.1.0"
__maintainer__ = "TrackMe Limited, U.K."
__email__ = "support@trackme-solutions.com"
__status__ = "PRODUCTION"

# Phantom App imports
import phantom.app as phantom
from phantom.base_connector import BaseConnector
from phantom.action_result import ActionResult

# Usage of the consts file is recommended
# from trackme_consts import *
import requests
import json
from bs4 import BeautifulSoup


class RetVal(tuple):

    def __new__(cls, val1, val2=None):
        return tuple.__new__(RetVal, (val1, val2))


class TrackmeConnector(BaseConnector):

    def __init__(self):

        # Call the BaseConnectors init first
        super(TrackmeConnector, self).__init__()

        self._state = None

        # Variable to hold a base_url in case the app makes REST calls
        # Do note that the app json defines the asset config, so please
        # modify this as you deem fit.
        self._splunk_url = None
        self._splunk_token = None
        self._verify_ssl = None
        self._headers = dict()

    def _process_empty_response(self, response, action_result):
        if response.status_code == 200:
            return RetVal(phantom.APP_SUCCESS, {})

        return RetVal(
            action_result.set_status(
                phantom.APP_ERROR, "Empty response and no information in the header"
            ), None
        )

    def _process_html_response(self, response, action_result):
        # An html response, treat it like an error
        status_code = response.status_code

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            error_text = soup.text
            split_lines = error_text.split('\n')
            split_lines = [x.strip() for x in split_lines if x.strip()]
            error_text = '\n'.join(split_lines)
        except:
            error_text = "Cannot parse error details"

        message = "Status Code: {0}. Data from server:\n{1}\n".format(status_code, error_text)

        message = message.replace(u'{', '{{').replace(u'}', '}}')
        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_json_response(self, r, action_result):
        # Try a json parse
        try:
            resp_json = r.json()
        except Exception as e:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR, "Unable to parse JSON response. Error: {0}".format(str(e))
                ), None
            )

        # Please specify the status codes here
        if 200 <= r.status_code < 399:
            return RetVal(phantom.APP_SUCCESS, resp_json)

        # You should process the error returned in the json
        message = "Error from server. Status Code: {0} Data from server: {1}".format(
            r.status_code,
            r.text.replace(u'{', '{{').replace(u'}', '}}')
        )

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _process_response(self, r, action_result):
        # store the r_text in debug data, it will get dumped in the logs if the action fails
        if hasattr(action_result, 'add_debug_data'):
            action_result.add_debug_data({'r_status_code': r.status_code})
            action_result.add_debug_data({'r_text': r.text})
            action_result.add_debug_data({'r_headers': r.headers})

        # Process each 'Content-Type' of response separately

        # Process a json response
        if 'json' in r.headers.get('Content-Type', ''):
            return self._process_json_response(r, action_result)

        # Process an HTML response, Do this no matter what the api talks.
        # There is a high chance of a PROXY in between phantom and the rest of
        # world, in case of errors, PROXY's return HTML, this function parses
        # the error and adds it to the action_result.
        if 'html' in r.headers.get('Content-Type', ''):
            return self._process_html_response(r, action_result)

        # it's not content-type that is to be parsed, handle an empty response
        if not r.text:
            return self._process_empty_response(r, action_result)

        # everything else is actually an error at this point
        message = "Can't process response from server. Status Code: {0} Data from server: {1}".format(
            r.status_code,
            r.text.replace('{', '{{').replace('}', '}}')
        )

        return RetVal(action_result.set_status(phantom.APP_ERROR, message), None)

    def _make_rest_call(self, endpoint, action_result, params=None, body=None, headers=None, method="get", **kwargs):
        # **kwargs can be any additional parameters that requests.request accepts

        config = self.get_config()
        
        if headers is None:
           headers = self._headers
        
        resp_json = None

        try:
            request_func = getattr(requests, method)
        except AttributeError:
            return RetVal(
                action_result.set_status(phantom.APP_ERROR, "Invalid method: {0}".format(method)),
                resp_json
            )

        # Create a URL to connect to
        url = self._splunk_url + endpoint
        
        ''' for debug purposes
        self.debug_print("url : " + url)
        self.debug_print(headers)
        self.debug_print(f"verify: {self._verify_ssl}")
        '''

        try:
            r = request_func(
                url,
                data=body,
                params=params,
                headers=headers,
                verify=self._verify_ssl,
                **kwargs
            )
        except Exception as e:
            return RetVal(
                action_result.set_status(
                    phantom.APP_ERROR, "Error Connecting to server. Details: {0}".format(str(e))
                ), resp_json
            )

        return self._process_response(r, action_result)

    def _handle_test_connectivity(self, param):
        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        self.save_progress("Connecting to endpoint")
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/vtenants/show_tenants', action_result, params=None, headers=self._headers
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success
        self.save_progress("Test Connectivity Passed")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_ack_get(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        object_category = param['object_category']
        object_list = param['object_list']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'object_category': object_category,
            'object_list': object_list,
        }

        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/ack/get_ack_for_object', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        try:
            ack_response = response[0]
        except Exception as e:
            ack_response = {
                'ack_comment': 'N/A',
                'ack_expiration': 'N/A',
                'ack_expiration_datetime': 'N/A',
                'ack_is_enabled': 0,
                'ack_mtime': 'N/A',
                'ack_mtime_datetime': 'N/A',
                'ack_state': 'inactive',
                'ack_type': 'N/A',
                'object': object_list,
                'object_category': object_category  
            }
        
        summary['trackme_response'] = json.dumps(ack_response)
        self.debug_print(f'ack_response: {ack_response}') 
        
        # add data
        action_result.add_data(ack_response)

        self.save_progress("Ack get successful")
        return action_result.set_status(phantom.APP_SUCCESS)


    def _handle_ack_manage(self, param):
        # Implement the handler here
        # use self.save_progress(...) to send progress messages back to the platform
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        object_category = param['object_category']
        object_list = param['object_list']
        action = param['action']
        ack_comment = param['ack_comment']
        ack_period = param['ack_period']
        ack_type = param['ack_type']
        update_comment = param['update_comment']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'object_category': object_category,
            'object_list': object_list,
            'action': action,
        }
        
        if ack_comment:
            body['ack_comment'] = ack_comment
        if ack_period:
            body['ack_period'] = ack_period
        if ack_type:
            body['ack_type'] = ack_type
        if update_comment:
            body['update_comment'] = update_comment

        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/ack/ack_manage', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        self.debug_print(f'response: {response}')
        process_count = response.get('process_count')
        success_count = response.get('success_count')
        failures_count = response.get('failures_count')

        summary['trackme_response'] = json.dumps(response)
        # self.debug_print(f'ack_response: {ack_response}') 
        
        # add data
        action_result.add_data(response)

        self.save_progress("Ack manage successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_maintenance_status(self, param):
        # Implement the handler here
        # use self.save_progress(...) to send progress messages back to the platform
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/maintenance/check_global_maintenance_status', action_result, method="get", body=None, params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        self.debug_print(f'response: {response}')        
        summary['trackme_response'] = json.dumps(response)
        
        # add data
        action_result.add_data(response)

        self.save_progress("Get maintenance mode successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_maintenance_enable(self, param):
        # Implement the handler here
        # use self.save_progress(...) to send progress messages back to the platform
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        add_knowledge_record = param.get('add_knowledge_record')
        maintenance_duration = param.get('maintenance_duration')
        maintenance_mode_end = param.get('maintenance_mode_end')
        maintenance_mode_start = param.get('maintenance_mode_start')
        time_format = param.get('time_format')
        update_comment = param.get('update_comment')
        
        # body
        body = {}
        
        if add_knowledge_record:
            body['add_knowledge_record'] = add_knowledge_record
        if maintenance_duration:
            body['maintenance_duration'] = maintenance_duration
        if maintenance_mode_end:
            body['maintenance_mode_end'] = maintenance_mode_end
        if maintenance_mode_start:
            body['maintenance_mode_start'] = maintenance_mode_start
        if time_format:
            body['time_format'] = time_format
        if update_comment:
            body['update_comment'] = update_comment

        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/maintenance/global_maintenance_enable', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        self.debug_print(f'response: {response}')

        summary['trackme_response'] = json.dumps(response)
        # self.debug_print(f'ack_response: {ack_response}') 
        
        # add data
        action_result.add_data(response)

        self.save_progress("Maintenance mode enable successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_maintenance_disable(self, param):
        # Implement the handler here
        # use self.save_progress(...) to send progress messages back to the platform
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        update_comment = param.get('update_comment')
        
        # body
        body = {}
        
        if update_comment:
            body['update_comment'] = update_comment

        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/maintenance/maintenance_disable', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        self.debug_print(f'response: {response}')

        summary['trackme_response'] = json.dumps(response)
        self.debug_print(f'maintenance_response: {response}') 
        
        # add data
        action_result.add_data(response)

        self.save_progress("Maintenance mode disable successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_ml_outliers_train_models(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        component = param['component']
        object_value = param['object']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'component': component,
            'object': object_value,
        }
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/splk_outliers_engine/write/outliers_train_models', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data
        action_result.add_data(response)

        self.save_progress("Machine Leaning Outliers training successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_mk_outliers_run_monitor(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        component = param['component']
        object_value = param['object']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'component': component,
            'object': object_value,
        }
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/splk_outliers_engine/write/outliers_mlmonitor_models', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data
        action_result.add_data(response)

        self.save_progress("Machine Leaning Outliers monitor successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_ml_outliers_reset_models(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        component = param['component']
        object_value = param['object']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'component': component,
            'object': object_value,
        }
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/splk_outliers_engine/write/outliers_reset_models', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data
        action_result.add_data(response)

        self.save_progress("Machine Leaning Outliers reset successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_ml_outliers_get_models(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        component = param['component']
        object_value = param['object']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'component': component,
            'object': object_value,
        }
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/splk_outliers_engine/outliers_get_rules', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data (response is a list)        
        for item in response:
             action_result.add_data(item)

        self.save_progress("Machine Leaning Outliers get successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_ml_outliers_add_period_exclusion(self, param):

        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        component = param['component']
        object_value = param['object']
        model_id = param['model_id']
        earliest = param['earliest']
        latest = param['latest']
        
        # body
        body = {
            'tenant_id': tenant_id,
            'component': component,
            'object': object_value,
            'action': 'add',
            'model_id': model_id,
            'earliest': earliest,
            'latest': latest,
        }
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/splk_outliers_engine/write/outliers_manage_model_period_exclusion', action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data
        action_result.add_data(response)

        self.save_progress("Machine Leaning Outliers add exclusion period successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_component_get_entity(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Parameters
        tenant_id = param['tenant_id']
        component = param['component']
        filter_key = param.get('filter_key')
        filter_object = param.get('filter_object')
        
        # This endpoints expects params especially
        params = {
            'tenant_id': tenant_id,
            'component': component,
        }
        
        if filter_key:
            params['filter_key'] = filter_key
        if filter_object:
            params['filter_object'] = filter_object
        
        # make rest call
        ret_val, response = self._make_rest_call(
            '/services/trackme/v2/component/load_component_data', action_result, method="get", body=None, params=params, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data (response is a list)
        data_response = response.get('data', [])
        for item in data_response:
             action_result.add_data(item)

        self.save_progress("Get TrackMe entity realtime data successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def _handle_component_manage_entity(self, param):
        self.save_progress("In action handler for: {0}".format(self.get_action_identifier()))

        # Add an action result object to self (BaseConnector) to represent the action for this param
        action_result = self.add_action_result(ActionResult(dict(param)))

        # Access action parameters passed in the 'param' dictionary

        # Required values can be accessed directly
        tenant_id = param['tenant_id']
        component = param['component']
        action = param['action']

        # Optional values should use the .get() function
        filter_object = param.get('filter_object', None)
        filter_key = param.get('filter_key', None)
        extra_attributes = param.get('extra_attributes', None)
        update_comment = param.get('update_comment', None)        

        # This endpoints expects params especially
        params = {
            'tenant_id': tenant_id,
            'component': component,
        }
        
        if filter_key:
            params['filter_key'] = filter_key
        if filter_object:
            params['filter_object'] = filter_object
            
        # try to parse extra_attributes from JSON string to an object
        try:
            extra_attributes = json.loads(extra_attributes)
        except Exception as e:
            pass
            
        # define the target endpoint depending on the requested action
        target_endpoint = None
        
        # init the rest body
        body = {
                 'tenant_id': tenant_id,   
        }
        
        # add filters
        if filter_object:
            body['object_list'] = filter_object
        elif filter_key:
            body['keys_list'] = filter_key
            
        # add update_comment
        if update_comment:
            body['update_comment'] = update_comment
        
        # handle action
        if action in ('enable', 'disable'):
            
            # add action to the body, this is expected by these endpoints
            body['action'] = action
            
            if component == 'dsm':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/ds_monitoring'
            elif component == 'dhm':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/dh_monitoring'
            elif component == 'mhm':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/mh_monitoring'
            elif component == 'wlk':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/wlk_monitoring'
            elif component == 'flx':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/flx_monitoring'

        elif action in ('delete'):
            
            # deletion type, attempt to retrieve from the key deletion_type in extra_attributes
            if extra_attributes:
                try:
                    deletion_type = extra_attributes['deletion_type']
                except Exception as e:
                    deletion_type = 'temporary'
                    
            # add to body
            body['deletion_type'] = deletion_type
            
            if component == 'dsm':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/ds_delete'
            elif component == 'dhm':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/dh_delete'
            elif component == 'mhm':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/mh_delete'
            elif component == 'wlk':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/wlk_delete'
            elif component == 'flx':
                target_endpoint = f'/services/trackme/v2/splk_{component}/write/flx_delete'
                
        # manage splk-dsm sampling
        elif action == 'manage_dsm_sampling':
            
            
            
            # get sampling action and details from extra_attributes
            if not extra_attributes:
                raise Exception(f'When request action={action}, you must provide in extra_attributes the requested action: enable|disable|reset|run|update_no_records')
            else:
                try:
                    sampling_action = extra_attributes['action']
                except Exception as e:
                    raise Exception('sampling action must be set in extra_attributes, valid actions are: enable|disable|reset|run|update_no_records')
                if sampling_action not in ('enable', 'disable', 'reset', 'run', 'update_no_records'):
                    raise Exception(f'Illegal action={sampling_action}, valid actions are: enable|disable|reset|run|update_no_records')
                else:
                    body['action'] = sampling_action
                
            # handle sampling action
            if sampling_action in ('enable', 'disable', 'reset', 'run'):
                
                # set endpoint
                target_endpoint = f'/services/trackme/v2/splk_dsm/write/ds_manage_data_sampling'
                
            elif sampling_action in ('update_no_records'):
                
                # set endpoint
                target_endpoint = f'/services/trackme/v2/splk_dsm/write/ds_update_data_sampling_records_nr'
                
                # retrieve the number of records requested (data_sampling_nr)
                try:
                    data_sampling_nr = extra_attributes['data_sampling_nr']
                    if not instance(data_sampling_nr, int):
                        raise Exception(f'action={action} requires data_sampling_nr to be set in extra_attributes as an integer value.')
                        
                    else:
                        body['data_sampling_nr'] = data_sampling_nr
                        
                except Exception as e:
                    raise Exception(f'action={action} requires data_sampling_nr to be set in extra_attributes as an integer value.')
                
        # make rest call
        ret_val, response = self._make_rest_call(
            target_endpoint, action_result, method="post", body=json.dumps(body), params=None, headers=None
        )

        if phantom.is_fail(ret_val):
            return action_result.get_status()

        # Return success

        # Add a dictionary that is made up of the most important values from data into the summary
        summary = action_result.update_summary({})
        
        # resp_data
        # self.debug_print(f'response: {response}')
        summary['trackme_response'] = json.dumps(response)
        
        # add data
        action_result.add_data(response)

        self.save_progress("Manage TrackMe entity successful")
        return action_result.set_status(phantom.APP_SUCCESS)

    def handle_action(self, param):
        ret_val = phantom.APP_SUCCESS

        # Get the action that we are supposed to execute for this App Run
        action_id = self.get_action_identifier()

        self.debug_print("action_id", self.get_action_identifier())

        if action_id == 'ack_get':
            ret_val = self._handle_ack_get(param)

        if action_id == 'ack_manage':
            ret_val = self._handle_ack_manage(param)

        if action_id == 'maintenance_status':
            ret_val = self._handle_maintenance_status(param)

        if action_id == 'maintenance_enable':
            ret_val = self._handle_maintenance_enable(param)

        if action_id == 'maintenance_disable':
            ret_val = self._handle_maintenance_disable(param)

        if action_id == 'ml_outliers_train_models':
            ret_val = self._handle_ml_outliers_train_models(param)

        if action_id == 'mk_outliers_run_monitor':
            ret_val = self._handle_mk_outliers_run_monitor(param)

        if action_id == 'ml_outliers_reset_models':
            ret_val = self._handle_ml_outliers_reset_models(param)

        if action_id == 'ml_outliers_get_models':
            ret_val = self._handle_ml_outliers_get_models(param)

        if action_id == 'ml_outliers_add_period_exclusion':
            ret_val = self._handle_ml_outliers_add_period_exclusion(param)

        if action_id == 'component_get_entity':
            ret_val = self._handle_component_get_entity(param)

        if action_id == 'component_manage_entity':
            ret_val = self._handle_component_manage_entity(param)

        if action_id == 'test_connectivity':
            ret_val = self._handle_test_connectivity(param)

        return ret_val

    def initialize(self):
        # Load the state in initialize, use it to store data
        # that needs to be accessed across actions
        self._state = self.load_state()

        # get the asset config
        config = self.get_config()
        """
        # Access values in asset config by the name

        # Required values can be accessed directly
        required_config_name = config['required_config_name']

        # Optional values should use the .get() function
        optional_config_name = config.get('optional_config_name')
        """

        self._base_url = config.get('base_url')
        self._splunk_url = config.get('splunk_url')
        self._verify_ssl = config.get('verify_ssl')
        self._splunk_token = config.get('splunk_token')
        self._headers = {'Authorization': f'Bearer {self._splunk_token}'}

        return phantom.APP_SUCCESS

    def finalize(self):
        # Save the state, this data is saved across actions and app upgrades
        self.save_state(self._state)
        return phantom.APP_SUCCESS


def main():
    import argparse

    argparser = argparse.ArgumentParser()

    argparser.add_argument('input_test_json', help='Input Test JSON file')
    argparser.add_argument('-u', '--username', help='username', required=False)
    argparser.add_argument('-p', '--password', help='password', required=False)

    args = argparser.parse_args()
    session_id = None

    username = args.username
    password = args.password

    if username is not None and password is None:

        # User specified a username but not a password, so ask
        import getpass
        password = getpass.getpass("Password: ")

    if username and password:
        try:
            login_url = TrackmeConnector._get_phantom_base_url() + '/login'

            print("Accessing the Login page")
            r = requests.get(login_url, verify=False)
            csrftoken = r.cookies['csrftoken']

            data = dict()
            data['username'] = username
            data['password'] = password
            data['csrfmiddlewaretoken'] = csrftoken

            headers = dict()
            headers['Cookie'] = 'csrftoken=' + csrftoken
            headers['Referer'] = login_url

            print("Logging into Platform to get the session id")
            r2 = requests.post(login_url, verify=False, data=data, headers=headers)
            session_id = r2.cookies['sessionid']
        except Exception as e:
            print("Unable to get session id from the platform. Error: " + str(e))
            exit(1)

    with open(args.input_test_json) as f:
        in_json = f.read()
        in_json = json.loads(in_json)
        print(json.dumps(in_json, indent=4))

        connector = TrackmeConnector()
        connector.print_progress_message = True

        if session_id is not None:
            in_json['user_session_token'] = session_id
            connector._set_csrf_info(csrftoken, headers['Referer'])

        ret_val = connector._handle_action(json.dumps(in_json), None)
        print(json.dumps(json.loads(ret_val), indent=4))

    exit(0)


if __name__ == '__main__':
    main()
