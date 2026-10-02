import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'storybook_web.settings')
django.setup()

import pytest
from django.test import Client
from django.urls import reverse
from unittest.mock import patch

def test_index_view():
    client = Client()
    response = client.get(reverse('story_index'))
    assert response.status_code == 200
    assert b"Storybook Studio" in response.content
    assert b"Library" in response.content


def test_create_view_get():
    client = Client()
    response = client.get(reverse('story_create'))
    assert response.status_code == 200
    assert b"Create New Picture Book" in response.content


@patch('story_app.services.start_story_job')
def test_create_view_post(mock_start_job):
    mock_start_job.return_value = "test-fox-story-12345678"
    client = Client()
    response = client.post(reverse('story_create'), {'concept': 'A friendly fox'})
    assert response.status_code == 302
    assert response.url == reverse('story_progress', kwargs={'story_id': 'test-fox-story-12345678'})
    mock_start_job.assert_called_once_with('A friendly fox')


def test_settings_view():
    client = Client()
    response = client.get(reverse('settings'))
    assert response.status_code == 200
    assert b"Style Specification" in response.content


@patch('story_app.services.resume_story')
def test_resume_story_view(mock_resume):
    mock_resume.return_value = "fox-story-123"
    client = Client()
    response = client.post(reverse('resume_story', kwargs={'story_id': 'fox-story-123'}))
    assert response.status_code == 302
    assert response.url == reverse('story_reader', kwargs={'story_id': 'fox-story-123'})
    mock_resume.assert_called_once_with('fox-story-123')


@patch('story_app.services.restart_story')
def test_restart_story_view(mock_restart):
    mock_restart.return_value = "fox-story-123"
    client = Client()
    response = client.post(reverse('restart_story', kwargs={'story_id': 'fox-story-123'}))
    assert response.status_code == 302
    assert response.url == reverse('story_reader', kwargs={'story_id': 'fox-story-123'})
    mock_restart.assert_called_once_with('fox-story-123')
