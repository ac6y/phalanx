########################################
Overview of Helm charts for applications
########################################

This page provides overall guidelines on how Phalanx uses Helm charts for applications.

Charts
======

Argo CD manages applications in the Rubin Science Platform through a set of Helm charts.
Which Helm charts to deploy in a given environment is controlled by the ``values-<environment>.yaml`` files in `/science-platform <https://github.com/lsst-sqre/phalanx/tree/master/science-platform/>`__.

The `/services <https://github.com/lsst-sqre/phalanx/tree/master/services/>`__ directory defines templates in its ``templates`` directory and values to resolve those templates in ``values.yaml`` and ``values-<environment>.yaml`` files to customize the application for each environment.  For first-party charts, the ``templates`` directory is generally richly populated.

For third-party charts the ``templates`` directory might not exist or might have only a small set of resources specific to the Science Platform.
In that case, most of the work of deploying an application is done by charts declared as dependencies (via the ``dependencies`` key in ``Chart.yaml``) of the top-level chart.
By convention, the top-level chart has the same name as the underlying chart that it deploys.
Subcharts may be external third-party Helm charts provided by other projects, or, in rare instances, they may be Helm charts maintained by Rubin Observatory.
In the latter case, these charts are maintained in the `lsst-sqre/charts GitHub repository <https://github.com/lsst-sqre/charts/>`__.

.. _chart-versioning:

Chart versioning
================

The top level of charts defined in the ``/services`` directory are used only by Argo CD and are never published as Helm charts.
Their versions are therefore irrelevant.
The version of each chart is set to ``1.0.0`` because ``version`` is a required field in ``Chart.yaml`` and then never changed.
It is instead the ``appVersion`` field that is used to point to a particular release of a first-person chart.  Reverting to a previous configuration in this layer of charts is done via a manual revert in Argo CD or by reverting a change in the GitHub repository so that the ``appVersion`` points to an earlier release.  It is **not** done by pointing Argo CD to an older chart.

Third-party charts are declared as dependencies; they are normal, published Helm charts that follow normal Helm semantic versioning conventions.
In the case of the ``lsst-sqre/charts`` repository, this is enforced by CI.
We can then constrain the version of the chart Argo CD will deploy by changing the ``dependencies`` configuration in the top-level chart.

Best practice is for a release of a chart to deploy the latest version of the corresponding application, so that upgrading the chart also implies upgrading the application.
This allows automatic creation of pull requests to upgrade any applications deployed by Argo CD (see :sqr:`042`).
Charts maintained as first-party charts in Phalanx follow this convention (for the most part).
Most upstream charts also follow this convention, but some require explicitly changing version numbers in ``values-*.yaml``.

In general, we pin the version of the chart to deploy in the ``dependencies`` metadata of the top-level chart.
This ensures deterministic cluster configuration and avoids inadvertently upgrading applications.
However, for applications still under development, we sometimes use a floating dependency to reduce the number of pull requests required when iterating, and then switch to a pinned version once the application is stable.

There is currently no generic mechanism to deploy different versions of a chart in different environments, as appVersion is set in ``Chart.yaml``.

That does not mean that rolling out a new version is all-or-nothing: you have a couple of different options for testing new versions.
The easiest is to modify the appVersion in ``Chart.yaml`` on your development branch and then use Argo CD to deploy the application from the branch, rather than ``master``, ``main``, or ``HEAD`` (as the case may be).
This will cause the application resource in the ``science-platform`` app to show as out of sync, which is indeed correct, and a helpful reminder that you may be running from a branch when you forget and subsequently rediscover that fact weeks later.
Additionally, many charts allow specification of a tag (usually some variable like ``image.tag`` in a values file), so that is a possibility as well.
If your chart doesn't have a way to control what image tag you're deploying from, consider adding the capability.
In any event, for RSP instances, we (as a matter of policy) disable automatic deployment in Argo CD so there is a human check on whether a given chart is safe to deploy in a given environment, and updates are deployed to production environments (barring extraordinary circumstances) during our specified maintenance windows.
