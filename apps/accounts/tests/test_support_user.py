"""Usuario de soporte de Ordo Lab dentro de un laboratorio (ADR-045).

Lo que estas pruebas fijan es la parte que NO es técnica: que el usuario sea **visible**
y que el laboratorio mande sobre él. Un soporte oculto sería otro diseño.
"""
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Membership, Role, User
from apps.accounts.services.user_management import (
    SUPPORT_USERNAME,
    create_support_user,
    set_support_password,
)


class UsuarioDeSoporteTests(TenantTestCase):
    def test_nace_sin_contrasena_utilizable(self):
        """Nadie puede entrar hasta que `clave_soporte` ponga una."""
        user = create_support_user()
        assert not user.has_usable_password()

    def test_es_administrador_del_laboratorio(self):
        create_support_user()
        user = User.objects.get(username=SUPPORT_USERNAME)
        assert user.memberships.get().role.code == Role.Code.ADMIN_LAB

    def test_se_ve_como_cualquier_otro_usuario(self):
        """No se esconde de ninguna consulta: es un usuario más, con nombre propio."""
        create_support_user()
        user = User.objects.get(username=SUPPORT_USERNAME)
        assert user in User.objects.all()
        assert user.is_active
        assert user.is_support
        assert f"{user.first_name} {user.last_name}" == "Soporte Ordo Lab"

    def test_crearlo_dos_veces_no_duplica(self):
        create_support_user()
        create_support_user()
        assert User.objects.filter(username=SUPPORT_USERNAME).count() == 1
        assert Membership.objects.filter(user__username=SUPPORT_USERNAME).count() == 1

    def test_la_clave_se_pone_despues(self):
        create_support_user()
        assert set_support_password(password="una-clave-larga-de-prueba") is True
        assert User.objects.get(username=SUPPORT_USERNAME).check_password(
            "una-clave-larga-de-prueba")

    def test_el_laboratorio_puede_desactivarlo(self):
        """Y desactivado se queda: poner la clave no lo revive."""
        create_support_user()
        User.objects.filter(username=SUPPORT_USERNAME).update(is_active=False)
        set_support_password(password="otra-clave-larga-de-prueba")
        assert not User.objects.get(username=SUPPORT_USERNAME).is_active

    def test_si_el_laboratorio_lo_borro_no_se_recrea_solo(self):
        """Volver a ponerlo en silencio sería la cuenta oculta que este diseño evita."""
        create_support_user()
        User.objects.filter(username=SUPPORT_USERNAME).delete()
        assert set_support_password(password="una-clave-larga-de-prueba") is False
        assert not User.objects.filter(username=SUPPORT_USERNAME).exists()
