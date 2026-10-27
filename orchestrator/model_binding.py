"""Registered execution choices resolved from trusted backend authority.

Model replies are preserved as intent. They cannot override the selected model
or reasoning effort for operations declaring this binding. Standalone operation
admissions still supply an explicit backend/parameter contract.
"""
import copy


def validate(binding, schema):
    if (set(binding)!={'provider','parameters'} or not isinstance(binding['provider'],str)
            or not isinstance(binding['parameters'],dict) or not binding['parameters']
            or not set(binding['parameters'])<=set(schema['properties'])
            or any(v not in ('model','reasoning') for v in binding['parameters'].values())):
        raise ValueError('Invalid registered backend parameter binding')


def fields(capability):
    from .execution import adapter
    return adapter(capability).backend_binding.get('parameters',{})


def bind(capability, parameters, backend):
    from .execution import adapter
    from .executors import provider_for
    binding=adapter(capability).backend_binding
    result=copy.deepcopy(parameters)
    if not binding:return result
    if provider_for(backend)!=binding['provider']:
        raise ValueError('Operation backend binding differs from authorized provider')
    for target,source in binding['parameters'].items():
        value=backend.get(source)
        if not isinstance(value,str) or not value:raise ValueError('Missing authorized backend field: '+source)
        result[target]=value
    return result


def verify(capability, parameters, backend):
    if bind(capability,parameters,backend)!=parameters:
        raise ValueError('Operation model parameters differ from frozen backend authority')


def selected(grant, capability, owner_backend):
    """A trusted tool configuration is independent of the agent's model."""
    return copy.deepcopy(grant.get('operation_backends',{}).get(capability,owner_backend))


def owner_fields(grant, capability):
    result=dict(fields(capability))
    if capability in grant.get('operation_backends',{}):
        # Legacy model-backed adapters declare a model parameter but have no
        # agent-backend binding. Explicit tool configuration owns that field.
        result.setdefault('model','model')
    return result


def bind_owner(grant, capability, parameters, owner_backend):
    backend=selected(grant,capability,owner_backend)
    result=bind(capability,parameters,backend)
    for target,source in owner_fields(grant,capability).items():
        value=backend.get(source)
        if not isinstance(value,str) or not value:raise ValueError('Missing authorized tool backend field: '+source)
        result[target]=value
    return result


def validate_grant(grant):
    from . import execution,executors
    configured=grant.get('operation_backends',{})
    if not isinstance(configured,dict) or not set(configured)<=set(grant['operations']):
        raise ValueError('Tool backend must name an explicitly granted operation')
    for cap,backend in configured.items():
        executors.validate(backend)
        provider=execution.MODEL_PROVIDERS.get(cap)
        if not provider or executors.provider_for(backend)!=provider or 'model' not in execution.parameter_schema(cap)['properties']:
            raise ValueError('Tool backend differs from registered operation provider')
        bind_owner(grant,cap,{},backend)
