from django.db import migrations


class Migration(migrations.Migration):
    """
    Remove legacy soft-delete columns that still exist in the PostgreSQL
    appointments_patientbookingrequest table but are no longer part of the
    current PatientBookingRequest model or migration state.

    Legacy database-only columns:
        - is_deleted
        - deleted_at
        - deleted_by_id

    Django's model state is already correct, so this migration changes only
    the physical database schema.
    """

    dependencies = [
        ("appointments", "0007_notification_action_url_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE appointments_patientbookingrequest
                            DROP COLUMN IF EXISTS deleted_by_id;

                        ALTER TABLE appointments_patientbookingrequest
                            DROP COLUMN IF EXISTS deleted_at;

                        ALTER TABLE appointments_patientbookingrequest
                            DROP COLUMN IF EXISTS is_deleted;
                    """,
                    reverse_sql="""
                        ALTER TABLE appointments_patientbookingrequest
                            ADD COLUMN is_deleted boolean NOT NULL DEFAULT FALSE;

                        ALTER TABLE appointments_patientbookingrequest
                            ALTER COLUMN is_deleted DROP DEFAULT;

                        ALTER TABLE appointments_patientbookingrequest
                            ADD COLUMN deleted_at timestamp with time zone NULL;

                        ALTER TABLE appointments_patientbookingrequest
                            ADD COLUMN deleted_by_id bigint NULL;

                        ALTER TABLE appointments_patientbookingrequest
                            ADD CONSTRAINT appointments_patient_deleted_by_id_db456a38_fk_accounts_
                            FOREIGN KEY (deleted_by_id)
                            REFERENCES accounts_user(id)
                            DEFERRABLE INITIALLY DEFERRED;

                        CREATE INDEX appointments_patientbookingrequest_deleted_by_id_db456a38
                            ON appointments_patientbookingrequest (deleted_by_id);

                        CREATE INDEX appointments_patientbookingrequest_is_deleted_4d71ae29
                            ON appointments_patientbookingrequest (is_deleted);
                    """,
                ),
            ],
            state_operations=[],
        ),
    ]
