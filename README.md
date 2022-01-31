# oservices
Services and components management


## Definitions
* **Package**: python package
* **Service**: system that provides a public api via a port. Can contain multiple processes.
* **Component**: element of a service. Only one long-running process by component. In certain cases, this process may create and kill other processes. These must
be strongly dependant on the main process, or else create a different component.
* **System**: multi-services working together
* **Neutral**: does not require a setup to be imported
* **Configuration**: in memory placeholder for configuration variables. May be dumped and loaded to file. Can be attached to a package, a service or a component.
* **Settings**: placeholder for a small set of variables, depending on where is installed a component, that will be loaded on thread awakening and propagated to all concerned configuration objects.
* **Administrator**: system that manages administration for a pool of components. These components may be attached to different services.

## Workflow

* **Configure a configuration**: set all conf variables
* **Configure a service**: configure all configurations of service
* **Setup**: setup django and logging
* **Initialize**: initialize files
* **Build**: generate configuration files

## API management

### Package
* A package exposes it's public objects, functions and classes through the __init__ file.
* A package has a conf.py file if needed. It is not necessarily stored in admin package.

### Service
* A service is a package containing a __service__.md file. This file explains where the different components are, especially the public api component.
* A service contains components, and may contain neutral files (like package files).
* All service configuration related files must live in the admin package, with correctly named files.

### Component
* A component is a package containing a __component__.py file.
* A component only exposes it's CONF, CONFIGURATION, Client and Mock

## Signals
Exit signals are only managed if components are started in processes. If run in main process, the caller needs to manage.

