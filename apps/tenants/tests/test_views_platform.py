"""Permisos del panel de plataforma (Fase 12). No usa TenantClient (eso probaría el
dominio de un laboratorio, no el de `public`): llama las vistas directamente con
RequestFactory, fijando `request.urlconf` a `config.urls_public` a mano — lo que
TenantMainMiddleware haría en una petición real contra el esquema `public`."""
import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import set_urlconf

from apps.accounts.models import User
from apps.tenants import views


@pytest.fixture(autouse=True)
def _public_urlconf():
    set_urlconf("config.urls_public")
    yield
    set_urlconf(None)


def _request(path="/"):
    request = RequestFactory().get(path)
    request.urlconf = "config.urls_public"
    request.tenant = None
    return request


@pytest.mark.django_db
def test_dashboard_redirige_a_login_si_no_hay_sesion():
    request = _request()
    request.user = AnonymousUser()
    response = views.dashboard(request)
    assert response.status_code == 302


@pytest.mark.django_db
def test_dashboard_403_si_no_es_superusuario():
    user = User.objects.create_user(username="normal12", password="x")
    request = _request()
    request.user = user
    with pytest.raises(PermissionDenied):
        views.dashboard(request)


@pytest.mark.django_db
def test_dashboard_200_si_es_superusuario():
    user = User.objects.create_user(username="root12", password="x", is_superuser=True)
    request = _request()
    request.user = user
    response = views.dashboard(request)
    assert response.status_code == 200


@pytest.mark.django_db
def test_tenant_list_200_si_es_superusuario():
    user = User.objects.create_user(username="root12b", password="x", is_superuser=True)
    request = _request("/panel/laboratorios/")
    request.user = user
    response = views.tenant_list(request)
    assert response.status_code == 200


@pytest.mark.django_db
def test_plan_list_200_si_es_superusuario():
    user = User.objects.create_user(username="root12c", password="x", is_superuser=True)
    request = _request("/panel/planes/")
    request.user = user
    response = views.plan_list(request)
    assert response.status_code == 200
