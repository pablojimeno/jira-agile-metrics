import pytest
from pandas import NaT, Timestamp, Timedelta

from ..conftest import (
    FauxJIRA as JIRA,
    FauxIssue as Issue,
    FauxChange as Change,
    FauxFieldValue as Value
)

from ..querymanager import QueryManager
from .cycletime import CycleTimeCalculator

@pytest.fixture
def jira(custom_fields):
    return JIRA(fields=custom_fields, issues=[
        Issue("A-1",
            summary="Just created",
            issuetype=Value("Story", "story"),
            status=Value("Backlog", "backlog"),
            resolution=None,
            created="2018-01-01 01:01:01",
            customfield_001="Team 1",
            customfield_002=Value(None, 10),
            customfield_003=Value(None, ["R2", "R3", "R4"]),
            changes=[],
        ),
        Issue("A-2",
            summary="Started",
            issuetype=Value("Story", "story"),
            status=Value("Next", "next"),
            resolution=None,
            created="2018-01-02 01:01:01",
            customfield_001="Team 1",
            customfield_002=Value(None, 20),
            customfield_003=Value(None, []),
            changes=[
                Change("2018-01-03 01:01:01", [("status", "Backlog", "Next",)]),
            ],
        ),
        Issue("A-3",
            summary="Completed",
            issuetype=Value("Story", "story"),
            status=Value("Done", "done"),
            resolution=Value("Done", "Done"),
            created="2018-01-03 01:01:01",
            customfield_001="Team 1",
            customfield_002=Value(None, 30),
            customfield_003=Value(None, []),
            changes=[
                Change("2018-01-03 01:01:01", [("status", "Backlog", "Next",)]),
                Change("2018-01-04 01:01:01", [("status", "Next", "Build",)]),
                Change("2018-01-05 01:01:01", [("status", "Build", "QA",)]),
                Change("2018-01-06 01:01:01", [("status", "QA", "Done",)]),
            ],
        ),
        Issue("A-4",
            summary="Moved back",
            issuetype=Value("Story", "story"),
            status=Value("Next", "next"),
            resolution=None,
            created="2018-01-04 01:01:01",
            customfield_001="Team 1",
            customfield_002=Value(None, 30),
            customfield_003=Value(None, []),
            changes=[
                Change("2018-01-04 01:01:01", [("status", "Backlog", "Next",)]),
                Change("2018-01-05 01:01:01", [("status", "Next", "Build",)]),
                Change("2018-01-06 01:01:01", [("status", "Build", "Next",)]),
            ],
        ),
    ])

@pytest.fixture
def settings(custom_settings):
    return custom_settings

def test_columns(jira, settings):
    query_manager = QueryManager(jira, settings)
    results = {}
    calculator = CycleTimeCalculator(query_manager, settings, results)

    data = calculator.run()

    assert list(data.columns) == [
        'key',
        'url',
        'issue_type',
        'summary',
        'status',
        'resolution',

        'Estimate',
        'Release',
        'Team',
        
        'cycle_time',
        'completed_timestamp',
        
        'Backlog',
        'Committed',
        'Build',
        'Test',
        'Done'
    ]

def test_empty(custom_fields, settings):
    jira = JIRA(fields=custom_fields, issues=[])
    query_manager = QueryManager(jira, settings)
    results = {}
    calculator = CycleTimeCalculator(query_manager, settings, results)

    data = calculator.run()

    assert len(data.index) == 0

def test_movement(jira, settings):
    query_manager = QueryManager(jira, settings)
    results = {}
    calculator = CycleTimeCalculator(query_manager, settings, results)

    data = calculator.run()

    assert data.to_dict('records') == [{
        'key': 'A-1',
        'url': 'https://example.org/browse/A-1',
        'issue_type': 'Story',
        'summary': 'Just created',
        'status': 'Backlog',
        'resolution': None,

        'Estimate': 10,
        'Release': 'R3',
        'Team': 'Team 1',

        'completed_timestamp': NaT,
        'cycle_time': NaT,

        'Backlog': Timestamp('2018-01-01 01:01:01'),
        'Committed': NaT,
        'Build': NaT,
        'Test': NaT,
        'Done': NaT,
    }, {
        'key': 'A-2',
        'url': 'https://example.org/browse/A-2',
        'issue_type': 'Story',
        'summary': 'Started',
        'status': 'Next',
        'resolution': None,

        'Estimate': 20,
        'Release': 'None',
        'Team': 'Team 1',

        'completed_timestamp': NaT,
        'cycle_time': NaT,

        'Backlog': Timestamp('2018-01-02 01:01:01'),
        'Committed': Timestamp('2018-01-03 01:01:01'),
        'Build': NaT,
        'Test': NaT,
        'Done': NaT,
    }, {
        'key': 'A-3',
        'url': 'https://example.org/browse/A-3',
        'summary': 'Completed',
        'issue_type': 'Story',
        'status': 'Done',
        'resolution': 'Done',

        'Estimate': 30,
        'Release': 'None',
        'Team': 'Team 1',

        'completed_timestamp': Timestamp('2018-01-06 01:01:01'),
        'cycle_time': Timedelta('3 days 00:00:00'),

        'Backlog': Timestamp('2018-01-03 01:01:01'),
        'Committed': Timestamp('2018-01-03 01:01:01'),
        'Build': Timestamp('2018-01-04 01:01:01'),
        'Test': Timestamp('2018-01-05 01:01:01'),
        'Done': Timestamp('2018-01-06 01:01:01'),
    }, {
        'key': 'A-4',
        'url': 'https://example.org/browse/A-4',
        'summary': 'Moved back',
        'issue_type': 'Story',
        'status': 'Next',
        'resolution': None,

        'Estimate': 30,
        'Release': 'None',
        'Team': 'Team 1',
        
        'completed_timestamp': NaT,
        'cycle_time': NaT,

        'Backlog': Timestamp('2018-01-04 01:01:01'),
        'Committed': Timestamp('2018-01-04 01:01:01'),
        'Build': NaT,
        'Test': NaT,
        'Done': NaT,
    }]
