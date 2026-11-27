"""桥接层透传绑定：确认 50 个公开名称绑定到正确的 wrapt 对象。

funcpatch 承诺透传 wrapt 能力、不重造轮子。本测试逐个核对身份绑定，
防止误绑、错绑或用自研实现替换 wrapt 对象。核心工具的实际行为另见
test_bridge_semantics.py 与 test_feature_parity.py。
"""

from __future__ import annotations

import inspect

import wrapt
import wrapt.importer  # pyright: ignore[reportMissingImports]

import funcpatch


def test_bridge_all_count_is_fifty():
    import funcpatch.bridge as bridge

    assert len(bridge.__all__) == 50


def test_proxy_classes_bind_to_wrapt():
    assert funcpatch.ObjectProxy is wrapt.ObjectProxy
    assert funcpatch.BaseObjectProxy is wrapt.BaseObjectProxy
    assert funcpatch.CallableObjectProxy is wrapt.CallableObjectProxy
    assert funcpatch.FunctionWrapper is wrapt.FunctionWrapper
    assert funcpatch.BoundFunctionWrapper is wrapt.BoundFunctionWrapper
    assert funcpatch.PartialCallableObjectProxy is wrapt.PartialCallableObjectProxy
    assert funcpatch.AutoObjectProxy is wrapt.AutoObjectProxy
    assert funcpatch.LazyObjectProxy is wrapt.LazyObjectProxy
    assert funcpatch.WeakFunctionProxy is wrapt.WeakFunctionProxy
    assert funcpatch.AttributeWrapper is wrapt.AttributeWrapper


def test_partial_and_lazy_import_bind_to_wrapt():
    assert funcpatch.partial is wrapt.partial
    assert funcpatch.lazy_import is wrapt.lazy_import


def test_decorator_and_signature_bind_to_wrapt():
    assert funcpatch.decorator is wrapt.decorator
    assert funcpatch.function_wrapper is wrapt.function_wrapper
    assert funcpatch.lru_cache is wrapt.lru_cache
    assert funcpatch.adapter_factory is wrapt.adapter_factory
    assert funcpatch.AdapterFactory is wrapt.AdapterFactory
    assert funcpatch.bind_state_to_wrapper is wrapt.bind_state_to_wrapper
    assert funcpatch.with_signature is wrapt.with_signature
    assert funcpatch.with_doc is wrapt.with_doc


def test_call_convention_binds_to_wrapt():
    assert funcpatch.async_to_sync is wrapt.async_to_sync
    assert funcpatch.sync_to_async is wrapt.sync_to_async
    assert funcpatch.mark_as_sync is wrapt.mark_as_sync
    assert funcpatch.mark_as_async is wrapt.mark_as_async
    assert funcpatch.synchronized is wrapt.synchronized


def test_patch_and_chain_bind_to_wrapt():
    assert funcpatch.apply_patch is wrapt.apply_patch
    assert funcpatch.unwrap_object is wrapt.unwrap_object
    assert funcpatch.wrap_object is wrapt.wrap_object
    assert funcpatch.wrap_object_attribute is wrapt.wrap_object_attribute
    assert funcpatch.wrap_function_wrapper is wrapt.wrap_function_wrapper
    assert funcpatch.patch_function_wrapper is wrapt.patch_function_wrapper
    assert funcpatch.scoped_function_wrapper is wrapt.scoped_function_wrapper
    assert funcpatch.transient_function_wrapper is wrapt.transient_function_wrapper
    assert funcpatch.find_wrapper is wrapt.find_wrapper
    assert funcpatch.is_wrapped_by is wrapt.is_wrapped_by
    assert funcpatch.wrapper_chain is wrapt.wrapper_chain
    assert funcpatch.unwrapped is wrapt.unwrapped
    assert funcpatch.resolve_path is wrapt.resolve_path
    assert funcpatch.resolve_owner is wrapt.resolve_owner
    assert funcpatch.MISSING is wrapt.MISSING


def test_import_hooks_bind_to_wrapt():
    assert funcpatch.register_post_import_hook is wrapt.importer.register_post_import_hook
    assert funcpatch.discover_post_import_hooks is wrapt.importer.discover_post_import_hooks
    assert funcpatch.notify_module_loaded is wrapt.importer.notify_module_loaded
    assert funcpatch.when_imported is wrapt.importer.when_imported


def test_exception_classes_bind_to_wrapt():
    assert funcpatch.WraptPathResolutionError is wrapt.PathResolutionError
    assert funcpatch.TargetModuleNotFoundError is wrapt.TargetModuleNotFoundError
    assert funcpatch.WrapperNotFoundError is wrapt.WrapperNotFoundError
    assert funcpatch.WrapperNotOutermostError is wrapt.WrapperNotOutermostError
    assert funcpatch.WrapperNotInitializedError is wrapt.WrapperNotInitializedError
    assert funcpatch.WrapperChainTooDeepError is wrapt.WrapperChainTooDeepError
    assert all(
        inspect.isclass(c) and issubclass(c, Exception)
        for c in (
            funcpatch.WraptPathResolutionError,
            funcpatch.TargetModuleNotFoundError,
            funcpatch.WrapperNotFoundError,
            funcpatch.WrapperNotOutermostError,
            funcpatch.WrapperNotInitializedError,
            funcpatch.WrapperChainTooDeepError,
        )
    )


def test_object_proxy_delegates():
    proxy = funcpatch.ObjectProxy([1, 2, 3])
    assert list(proxy) == [1, 2, 3]
    assert proxy[0] == 1


def test_callable_object_proxy_calls_wrapped():
    def add(x: int) -> int:
        return x + 1

    proxy = funcpatch.CallableObjectProxy(add)
    assert proxy(1) == 2


def test_lazy_import_resolves_attribute():
    json_proxy = funcpatch.lazy_import("json")
    assert json_proxy.dumps({"a": 1}) == '{"a": 1}'


def test_with_doc_sets_docstring():
    @funcpatch.with_doc(doc="说明文本")
    def f():
        pass

    assert f.__doc__ == "说明文本"


def test_async_to_sync_runs_coroutine():
    @funcpatch.async_to_sync
    async def compute(x: int) -> int:
        return x * 2

    assert compute(3) == 6


def test_mark_as_async_keeps_async_generator_identity():
    @funcpatch.mark_as_async
    async def gen():
        yield 1

    assert inspect.isasyncgenfunction(gen)


def test_resolve_path_and_owner():
    import types

    module = types.ModuleType("bridge_probe")
    setattr(module, "value", 1)  # noqa: B010
    parent, attr, original = funcpatch.resolve_path(module, "value")
    assert parent is module and attr == "value" and original == 1
    assert funcpatch.resolve_owner(module, "value") == (module, "value", 1)
