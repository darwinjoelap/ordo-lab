from django.db import migrations


class Migration(migrations.Migration):
    """Instala `unaccent`, que es lo que permite buscar sin tildes.

    Va en una app **compartida** y con `WITH SCHEMA public` a propósito: una extensión es
    un objeto de base de datos, no de esquema, y crearla una vez en `public` basta para
    todos los laboratorios — django-tenants deja `public` en el `search_path` de cada uno.
    Puesta en una app de tenant se intentaría crear una copia por esquema.

    `IF NOT EXISTS` la hace idempotente. **Si el usuario de la base no tiene permiso para
    crear extensiones, esta migración falla y con ella el despliegue**; en Railway el
    usuario es superusuario, así que no aplica, pero conviene saberlo antes de mover el
    proyecto a otro proveedor.
    """

    dependencies = [("masterdata", "0002_officialrate")]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;",
            # Al revertir no se desinstala: otras consultas podrían estar usándola y
            # dejarla instalada no cuesta nada.
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
