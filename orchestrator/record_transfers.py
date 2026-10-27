"""Declared record-family transfers; no implicit parameter forwarding or dropping."""
import copy
from .runtime_outcomes import Hold


def defect(message):
    raise Hold('compiler_contract_incompatible', message, phase='compile', effect='none')


def contract(family):
    interface=family['planning_interface'];transfer=interface.get('merge_transfer')
    declared=set(interface['schema']['properties'])
    if (not isinstance(transfer,dict) or transfer.get('version')!=1 or
            set(transfer)!= {'version','parameters'} or set(transfer['parameters'])!=declared or
            any(v not in ('parameter','reviewed_artifact') for v in transfer['parameters'].values())):
        defect('Registered record merge transfer must account for every declared semantic parameter')
    return copy.deepcopy(transfer)


def project(family, parameters, paths, catalogs, reviews):
    from . import execution,parameter_contracts
    interface=family['planning_interface'];transfer=contract(family)
    if set(parameters)-set(transfer['parameters']):defect('Undeclared semantic parameter in generated merge')
    result={k:copy.deepcopy(v) for k,v in parameters.items() if transfer['parameters'][k]=='parameter'}
    result.update(paths,catalog_paths=catalogs,review_paths=reviews)
    try:parameter_contracts.validate(result,execution.parameter_schema(interface['merge_operation']))
    except ValueError as exc:defect('Generated '+interface['merge_operation']+' parameters violate registered consumer contract: '+str(exc))
    return result


def artifact_parameters(family, first):
    """Only exact bound, sealed and independently reviewed partitions may supply these."""
    transfer=contract(family)
    return {k:copy.deepcopy(first[k]) for k,mode in transfer['parameters'].items() if mode=='reviewed_artifact' and k in first}


def equal_policy(family,left,right):
    return all(left.get(k)==right.get(k) for k in contract(family)['parameters'])
