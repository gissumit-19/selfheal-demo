"""Self-healing CI/CD agent: real GitHub Actions, Jenkins, Argo CD and Airflow adapters."""
import os

# Use the operating system's certificate store (Windows/macOS/Linux) for every HTTPS call, instead of
# the SDKs' bundled CA list. Corporate networks that inspect HTTPS install their certificate in the OS
# store only; without this the model SDKs fail with APIConnectionError / CERTIFICATE_VERIFY_FAILED.
# Set HEAL_SYSTEM_CERTS=0 to turn it off.
if os.getenv("HEAL_SYSTEM_CERTS", "1") != "0":
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass
