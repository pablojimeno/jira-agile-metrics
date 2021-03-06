import json
import logging
import pandas as pd

from ..calculator import Calculator
from ..utils import get_extension, to_json_string, StatusTypes

logger = logging.getLogger(__name__)

class CycleTimeCalculator(Calculator):
    """Basic cycle time data, fetched from JIRA.

    Builds a numerically indexed data frame with the following 'fixed'
    columns: `key`, 'url', 'issue_type', `summary`, `status`, and
    `resolution` from JIRA, as well as the value of any fields set in
    the `fields` dict in `settings`. If `known_values` is set (a dict of
    lists, with field names as keys and a list of known values for each
    field as values) and a field in `fields` contains a list of values,
    only the first value in the list of known values will be used.

    If 'query_attribute' is set in `settings`, a column with this name
    will be added, and populated with the `value` key, if any, from each
    criteria block under `queries` in settings.

    In addition, `cycle_time` will be set to the time delta between the
    first `accepted`-type column and the first `complete` column, or None.

    The remaining columns are the names of the items in the configured
    cycle, in order.

    Each cell contains the last date/time stamp when the relevant status
    was set.

    If an item moves backwards through the cycle, subsequent date/time
    stamps in the cycle are erased.
    """

    def __init__(self, query_manager, settings, results):
        super().__init__(query_manager, settings, results)

        self.cycle_lookup = {}
        for idx, cycle_step in enumerate(self.settings['cycle']):
            for status in cycle_step['statuses']:
                self.cycle_lookup[status.lower()] = dict(
                    index=idx,
                    name=cycle_step['name'],
                    type=cycle_step['type'],
                )

    def run(self):
        cycle_names = [s['name'] for s in self.settings['cycle']]
        accepted_steps = set(s['name'] for s in self.settings['cycle'] if s['type'] == StatusTypes.accepted)
        completed_steps = set(s['name'] for s in self.settings['cycle'] if s['type'] == StatusTypes.complete)

        series = {
            'key': {'data': [], 'dtype': 'str'},
            'url': {'data': [], 'dtype': 'str'},
            'issue_type': {'data': [], 'dtype': 'str'},
            'summary': {'data': [], 'dtype': 'str'},
            'status': {'data': [], 'dtype': 'str'},
            'resolution': {'data': [], 'dtype': 'str'},
            'cycle_time': {'data': [], 'dtype': 'timedelta64[ns]'},
            'completed_timestamp': {'data': [], 'dtype': 'datetime64[ns]'}
        }

        for cycle_name in cycle_names:
            series[cycle_name] = {'data': [], 'dtype': 'datetime64[ns]'}

        for name in self.settings['attributes'].keys():
            series[name] = {'data': [], 'dtype': 'object'}

        if self.settings['query_attribute']:
            series[self.settings['query_attribute']] = {'data': [], 'dtype': 'str'}

        for criteria in self.settings['queries']:
            for issue in self.query_manager.find_issues(criteria['jql']):

                item = {
                    'key': issue.key,
                    'url': "%s/browse/%s" % (self.query_manager.jira._options['server'], issue.key,),
                    'issue_type': issue.fields.issuetype.name,
                    'summary': issue.fields.summary,
                    'status': issue.fields.status.name,
                    'resolution': issue.fields.resolution.name if issue.fields.resolution else None,
                    'cycle_time': None,
                    'completed_timestamp': None
                }

                for name in self.settings['attributes'].keys():
                    item[name] = self.query_manager.resolve_attribute_value(issue, name)

                if self.settings['query_attribute']:
                    item[self.settings['query_attribute']] = criteria.get('value', None)

                for cycle_name in cycle_names:
                    item[cycle_name] = None

                # Record date of status changes
                for snapshot in self.query_manager.iter_changes(issue, ['status']):
                    snapshot_cycle_step = self.cycle_lookup.get(snapshot.toString.lower(), None)
                    if snapshot_cycle_step is None:
                        logger.warn("Issue %s transitioned to unknown JIRA status %s", issue.key, snapshot.toString)
                        continue

                    snapshot_cycle_step_name = snapshot_cycle_step['name']

                    # Keep the first time we entered a step
                    if item[snapshot_cycle_step_name] is None:
                        item[snapshot_cycle_step_name] = snapshot.date

                    # Wipe any subsequent dates, in case this was a move backwards
                    found_cycle_name = False
                    for cycle_name in cycle_names:
                        if not found_cycle_name and cycle_name == snapshot_cycle_step_name:
                            found_cycle_name = True
                            continue
                        elif found_cycle_name and item[cycle_name] is not None:
                            logger.info("Issue %s moved backwards to %s, wiping data for subsequent step %s", issue.key, snapshot_cycle_step_name, cycle_name)
                            item[cycle_name] = None

                # Wipe timestamps if items have moved backwards; calculate cycle time

                previous_timestamp = None
                accepted_timestamp = None
                completed_timestamp = None

                for cycle_name in cycle_names:
                    if item[cycle_name] is not None:
                        previous_timestamp = item[cycle_name]

                        if accepted_timestamp is None and previous_timestamp is not None and cycle_name in accepted_steps:
                            accepted_timestamp = previous_timestamp
                        if completed_timestamp is None and previous_timestamp is not None and cycle_name in completed_steps:
                            completed_timestamp = previous_timestamp

                if accepted_timestamp is not None and completed_timestamp is not None:
                    item['cycle_time'] = completed_timestamp - accepted_timestamp
                    item['completed_timestamp'] = completed_timestamp

                for k, v in item.items():
                    series[k]['data'].append(v)

        data = {}
        for k, v in series.items():
            data[k] = pd.Series(v['data'], dtype=v['dtype'])

        return pd.DataFrame(data,
            columns=['key', 'url', 'issue_type', 'summary', 'status', 'resolution'] +
                    sorted(self.settings['attributes'].keys()) +
                    ([self.settings['query_attribute']] if self.settings['query_attribute'] else []) +
                    ['cycle_time', 'completed_timestamp'] +
                    cycle_names
        )

    def write(self):
        output_file = self.settings['cycle_time_data']
        
        if not output_file:
            logger.debug("No output file specified for cycle time data")
            return

        output_extension = get_extension(output_file)

        cycle_data = self.get_result()
        cycle_names = [s['name'] for s in self.settings['cycle']]
        attribute_names = sorted(self.settings['attributes'].keys())
        query_attribute_names = [self.settings['query_attribute']] if self.settings['query_attribute'] else []

        header = ['ID', 'Link', 'Name'] + cycle_names + ['Type', 'Status', 'Resolution'] + attribute_names + query_attribute_names
        columns = ['key', 'url', 'summary'] + cycle_names + ['issue_type', 'status', 'resolution'] + attribute_names + query_attribute_names

        logger.info("Writing cycle time data to %s", output_file)

        if output_extension == '.json':
            values = [header] + [list(map(to_json_string, row)) for row in cycle_data[columns].values.tolist()]
            with open(output_file, 'w') as out:
                out.write(json.dumps(values))
        elif output_extension == '.xlsx':
            cycle_data.to_excel(output_file, 'Cycle data', columns=columns, header=header, index=False)
        else:
            cycle_data.to_csv(output_file, columns=columns, header=header, date_format='%Y-%m-%d', index=False)
