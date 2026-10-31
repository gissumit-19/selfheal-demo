FROM jenkins/jenkins:lts-jdk21
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pytest && rm -rf /var/lib/apt/lists/*
USER jenkins
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
COPY casc.yaml /casc/casc.yaml
ENV CASC_JENKINS_CONFIG=/casc/casc.yaml
ENV JAVA_OPTS=-Djenkins.install.runSetupWizard=false
