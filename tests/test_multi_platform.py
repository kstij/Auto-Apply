'''
Unit and integration tests for Multi-Platform Indeed integration and Orchestration.
'''

import os
import json
import pytest
from modules.platforms.base_platform import BasePlatformBot
from modules.platforms.indeed_engine import IndeedBot
from modules.platforms.orchestrator import main as orchestrator_main
import config_schema
import app


def test_schema_includes_indeed_fields():
    '''Verify config schema contains Indeed fields and target_platform.'''
    valid = config_schema.valid_keys()
    assert "secrets" in valid
    assert "indeed_username" in valid["secrets"]
    assert "indeed_password" in valid["secrets"]
    assert "indeed_country_domain" in valid["secrets"]
    
    assert "search" in valid
    assert "indeed_base_url" in valid["search"]
    
    assert "settings" in valid
    assert "target_platform" in valid["settings"]


def test_indeed_bot_url_generation():
    '''Test Indeed search URL generation with custom parameters.'''
    bot = IndeedBot()
    bot.country_domain = "www.indeed.com"
    bot.base_url = ""
    url = bot.build_search_url("Software Engineer", "New York")
    assert "indeed.com/jobs" in url
    assert "q=Software+Engineer" in url
    assert "l=New+York" in url


def test_indeed_record_application(tmp_path, monkeypatch):
    '''Test recording an application to CSV with Platform column.'''
    monkeypatch.chdir(tmp_path)
    bot = IndeedBot()
    bot.record_application(
        job_id="test_indeed_123",
        title="Python Developer",
        company="Acme Corp",
        job_link="https://www.indeed.com/viewjob?jk=123"
    )
    assert bot.applied_count == 1
    csv_file = tmp_path / "all excels" / "all_applied_applications_history.csv"
    assert csv_file.exists()
    
    content = csv_file.read_text(encoding="utf-8")
    assert "test_indeed_123" in content
    assert "Indeed" in content
    assert "Acme Corp" in content


def test_app_bot_command_platform():
    '''Test that app._bot_command creates orchestrator arguments for different platforms.'''
    cmd_linkedin = app._bot_command("linkedin")
    assert "--platform" in cmd_linkedin
    assert "linkedin" in cmd_linkedin

    cmd_indeed = app._bot_command("indeed")
    assert "--platform" in cmd_indeed
    assert "indeed" in cmd_indeed

    cmd_glassdoor = app._bot_command("glassdoor")
    assert "--platform" in cmd_glassdoor
    assert "glassdoor" in cmd_glassdoor

    cmd_foundit = app._bot_command("foundit")
    assert "--platform" in cmd_foundit
    assert "foundit" in cmd_foundit


def test_glassdoor_and_foundit_instantiation():
    '''Test instantiation and URL building for Glassdoor and Foundit.'''
    from modules.platforms.glassdoor_engine import GlassdoorBot
    from modules.platforms.foundit_engine import FounditBot

    g_bot = GlassdoorBot()
    g_url = g_bot.build_search_url("Data Analyst", "Austin, TX")
    assert "glassdoor.com/Job" in g_url
    assert "keyword=Data+Analyst" in g_url

    f_bot = FounditBot()
    f_url = f_bot.build_search_url("Data Analyst", "Bangalore")
    assert "foundit.in/srp" in f_url
    assert "Data%20Analyst" in f_url

