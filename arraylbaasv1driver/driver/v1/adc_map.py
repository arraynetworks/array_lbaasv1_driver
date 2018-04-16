# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from neutron_lbaas.services.loadbalancer import constants as lb_const

def service_group_lb_method(method, session_persistence=None):
    lb_methods = {
        (None, lb_const.LB_METHOD_ROUND_ROBIN): ('RR', None, 'Default'),
        (None, lb_const.LB_METHOD_LEAST_CONNECTIONS): ('LC', None, 'Default'),
        (None, lb_const.LB_METHOD_SOURCE_IP): ('PI', None, 'Default'),
        (lb_const.SESSION_PERSISTENCE_HTTP_COOKIE, lb_const.LB_METHOD_ROUND_ROBIN): ('IC', 'rr', 'IC'),
        (lb_const.SESSION_PERSISTENCE_HTTP_COOKIE, lb_const.LB_METHOD_LEAST_CONNECTIONS): ('IC', 'lc', 'IC'),
        (lb_const.SESSION_PERSISTENCE_APP_COOKIE, lb_const.LB_METHOD_ROUND_ROBIN): ('HC', 'rr', 'PC'),
        (lb_const.SESSION_PERSISTENCE_APP_COOKIE, lb_const.LB_METHOD_LEAST_CONNECTIONS): ('HC', 'lc', 'PC'),
        (lb_const.SESSION_PERSISTENCE_SOURCE_IP, lb_const.LB_METHOD_ROUND_ROBIN): ('PI', 'rr', 'Default'),
        (lb_const.SESSION_PERSISTENCE_SOURCE_IP, lb_const.LB_METHOD_LEAST_CONNECTIONS): ('PI', 'lc', 'Default'),
        (None, lb_const.LB_METHOD_SOURCE_IP): ('HI', None, 'Default'),
        (lb_const.SESSION_PERSISTENCE_HTTP_COOKIE, lb_const.LB_METHOD_SOURCE_IP): ('HI', None, 'Default'),
        (lb_const.SESSION_PERSISTENCE_APP_COOKIE, lb_const.LB_METHOD_SOURCE_IP): ('HI', None, 'Default'),
        (lb_const.SESSION_PERSISTENCE_SOURCE_IP, lb_const.LB_METHOD_SOURCE_IP): ('HI', None, 'Default'),
    }

    return lb_methods.get((session_persistence, method), 'rr')
