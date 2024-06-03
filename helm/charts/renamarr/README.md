# renamarr helm chart

The chart defaults are recommended for the majority of users:

* Creates an hourly cronjob
* automatically checks for updates on startup
  * imageTag `latest`
  * imagePullPolicy `always`

If you wish to change the cron schedule:

* `.Values.cron.schedule`
* [custom-schedule-values.yaml](ci/custom-schedule-values.yaml)

If you wish to disable automatic updates, and run a fixed version:

* set `.Values.image.tag`
* [fixed-version-values.yaml](ci/fixed-version-values.yaml)
