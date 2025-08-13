
tests/test_cli/test_cli.py ....                                                                               [  0%]
tests/test_cli/test_debug_flags_no_llm.py FFFFFFFFFFF                                                         [  1%]
tests/test_cli/test_direct_execution_helpers.py ....................                                          [  2%]
tests/test_cli/test_dual_mode_stdin.py ...........                                                            [  3%]
tests/test_cli/test_json_error_handling.py .......                                                            [  4%]
tests/test_cli/test_main.py .............................                                                     [  6%]
tests/test_cli/test_workflow_output_handling.py ........................                                      [  8%]
tests/test_cli/test_workflow_save.py ....                                                                     [  8%]
tests/test_cli/test_workflow_save_integration.py .......                                                      [  9%]
tests/test_core/test_ir_examples.py ...................                                                       [ 10%]
tests/test_core/test_ir_schema.py .............................                                               [ 13%]
tests/test_core/test_workflow_interfaces.py ..................................                                [ 15%]
tests/test_core/test_workflow_manager.py ................................                                     [ 18%]
tests/test_docs/test_links.py .                                                                               [ 18%]
tests/test_integration/test_context_builder_integration.py ............                                       [ 19%]
tests/test_integration/test_context_builder_performance.py .........                                          [ 19%]
tests/test_integration/test_e2e_workflow.py ...........                                                       [ 20%]
tests/test_integration/test_git_commit_push_integration.py ....                                               [ 21%]
tests/test_integration/test_git_status_integration.py .......                                                 [ 21%]
tests/test_integration/test_metadata_flow.py ......                                                           [ 22%]
tests/test_integration/test_template_system_e2e.py .....                                                      [ 22%]
tests/test_integration/test_unused_inputs.py ...                                                              [ 22%]
tests/test_integration/test_workflow_manager_integration.py ..................                                [ 24%]
tests/test_nodes/test_echo.py .......                                                                         [ 24%]
tests/test_nodes/test_file/test_copy_file.py .....                                                            [ 25%]
tests/test_nodes/test_file/test_delete_file.py .....                                                          [ 25%]
tests/test_nodes/test_file/test_file_integration.py .....                                                     [ 25%]
tests/test_nodes/test_file/test_file_retry.py ..........                                                      [ 26%]
tests/test_nodes/test_file/test_move_file.py ....                                                             [ 27%]
tests/test_nodes/test_file/test_read_file.py ........                                                         [ 27%]
tests/test_nodes/test_file/test_write_file.py .........                                                       [ 28%]
tests/test_nodes/test_git/test_checkout.py ...................................                                [ 31%]
tests/test_nodes/test_git/test_commit.py ...............                                                      [ 32%]
tests/test_nodes/test_git/test_push.py .............                                                          [ 33%]
tests/test_nodes/test_git/test_status.py ........................                                             [ 35%]
tests/test_nodes/test_github/test_create_pr.py ................                                               [ 36%]
tests/test_nodes/test_github/test_get_issue.py .............                                                  [ 37%]
tests/test_nodes/test_github/test_list_issues.py ............                                                 [ 38%]
tests/test_nodes/test_llm/test_llm.py ........................                                                [ 40%]
tests/test_nodes/test_test_nodes.py ...........                                                               [ 41%]
tests/test_planning/integration/test_discovery_to_parameter_flow.py ............                              [ 42%]
tests/test_planning/integration/test_flow_structure.py ..........                                             [ 42%]
tests/test_planning/integration/test_generator_parameter_integration.py .............                         [ 44%]
tests/test_planning/integration/test_happy_path_mocked.py .............                                       [ 45%]
tests/test_planning/integration/test_parameter_management_integration.py ....                                 [ 45%]
tests/test_planning/integration/test_planner_integration.py .........                                         [ 46%]
tests/test_planning/integration/test_planner_simple.py ...                                                    [ 46%]
tests/test_planning/integration/test_planner_smoke.py ...                                                     [ 46%]
tests/test_planning/integration/test_planner_working.py ..                                                    [ 46%]
tests/test_planning/test_context_builder_phases.py ......................................                     [ 49%]
tests/test_planning/test_debug.py ...................FF.....                                                  [ 51%]
tests/test_planning/test_debug_integration.py ............                                                    [ 52%]
tests/test_planning/test_debug_utils.py ....................                                                  [ 54%]
tests/test_planning/test_ir_models.py .....................                                                   [ 55%]
tests/test_planning/test_registry_helper.py ................                                                  [ 57%]
tests/test_planning/test_workflow_loader.py ..........                                                        [ 57%]
tests/test_planning/test_workflow_loading.py ................                                                 [ 59%]
tests/test_planning/unit/test_browsing_selection.py ..^CFF..F                                                   [ 59%]
tests/test_planning/unit/test_discovery_error_handling.py ....^CF.F.^CF                                           [ 60%]
tests/test_planning/unit/test_discovery_routing.py ...F^CF                                                      [ 60%]
tests/test_planning/unit/test_generator.py ....F....F..FFFFFFF..
cli: Interrupted by user

INTERNALERROR> Traceback (most recent call last):
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/main.py", line 289, in wrap_session
INTERNALERROR>     session.exitstatus = doit(config, session) or 0
INTERNALERROR>                          ~~~~^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/main.py", line 343, in _main
INTERNALERROR>     config.hook.pytest_runtestloop(session=session)
INTERNALERROR>     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR>     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR>            ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR>     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR>            ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR>     raise exception
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/logging.py", line 801, in pytest_runtestloop
INTERNALERROR>     return (yield)  # Run all the tests.
INTERNALERROR>             ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/terminal.py", line 685, in pytest_runtestloop
INTERNALERROR>     result = yield
INTERNALERROR>              ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR>     res = hook_impl.function(*args)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/main.py", line 367, in pytest_runtestloop
INTERNALERROR>     item.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
INTERNALERROR>     ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR>     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR>            ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR>     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR>            ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR>     raise exception
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/warnings.py", line 90, in pytest_runtest_protocol
INTERNALERROR>     return (yield)
INTERNALERROR>             ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/assertion/__init__.py", line 192, in pytest_runtest_protocol
INTERNALERROR>     return (yield)
INTERNALERROR>             ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/unittest.py", line 427, in pytest_runtest_protocol
INTERNALERROR>     res = yield
INTERNALERROR>           ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/faulthandler.py", line 88, in pytest_runtest_protocol
INTERNALERROR>     return (yield)
INTERNALERROR>             ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR>     res = hook_impl.function(*args)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/runner.py", line 117, in pytest_runtest_protocol
INTERNALERROR>     runtestprotocol(item, nextitem=nextitem)
INTERNALERROR>     ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/runner.py", line 136, in runtestprotocol
INTERNALERROR>     reports.append(call_and_report(item, "call", log))
INTERNALERROR>                    ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/runner.py", line 248, in call_and_report
INTERNALERROR>     report: TestReport = ihook.pytest_runtest_makereport(item=item, call=call)
INTERNALERROR>                          ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR>     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR>            ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR>     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR>            ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR>     raise exception
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/tmpdir.py", line 308, in pytest_runtest_makereport
INTERNALERROR>     rep = yield
INTERNALERROR>           ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>     ~~~~~~~~~~~~~~^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/skipping.py", line 275, in pytest_runtest_makereport
INTERNALERROR>     rep = yield
INTERNALERROR>           ^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR>     res = hook_impl.function(*args)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/runner.py", line 368, in pytest_runtest_makereport
INTERNALERROR>     return TestReport.from_item_and_call(item, call)
INTERNALERROR>            ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/reports.py", line 377, in from_item_and_call
INTERNALERROR>     longrepr = item.repr_failure(excinfo)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/python.py", line 1712, in repr_failure
INTERNALERROR>     return self._repr_failure_py(excinfo, style=style)
INTERNALERROR>            ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/nodes.py", line 456, in _repr_failure_py
INTERNALERROR>     return excinfo.getrepr(
INTERNALERROR>            ~~~~~~~~~~~~~~~^
INTERNALERROR>         funcargs=True,
INTERNALERROR>         ^^^^^^^^^^^^^^
INTERNALERROR>     ...<5 lines>...
INTERNALERROR>         truncate_args=truncate_args,
INTERNALERROR>         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>     )
INTERNALERROR>     ^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/code.py", line 766, in getrepr
INTERNALERROR>     return fmt.repr_excinfo(self)
INTERNALERROR>            ~~~~~~~~~~~~~~~~^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/code.py", line 1202, in repr_excinfo
INTERNALERROR>     reprtraceback = self.repr_traceback(excinfo_)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/code.py", line 1135, in repr_traceback
INTERNALERROR>     self.repr_traceback_entry(entry, excinfo if last == entry else None)
INTERNALERROR>     ~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/code.py", line 1065, in repr_traceback_entry
INTERNALERROR>     source = self._getentrysource(entry)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/code.py", line 903, in _getentrysource
INTERNALERROR>     source = entry.getsource(self.astcache)
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/code.py", line 300, in getsource
INTERNALERROR>     astnode, _, end = getstatementrange_ast(
INTERNALERROR>                       ~~~~~~~~~~~~~~~~~~~~~^
INTERNALERROR>         self.lineno, source, astnode=astnode
INTERNALERROR>         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>     )
INTERNALERROR>     ^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/source.py", line 193, in getstatementrange_ast
INTERNALERROR>     start, end = get_statement_startend2(lineno, astnode)
INTERNALERROR>                  ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/.venv/lib/python3.13/site-packages/_pytest/_code/source.py", line 158, in get_statement_startend2
INTERNALERROR>     if isinstance(x, (ast.stmt, ast.ExceptHandler)):
INTERNALERROR>        ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/Users/andfal/projects/pflow/src/pflow/cli/main.py", line 31, in handle_sigint
INTERNALERROR>     sys.exit(130)  # Standard Unix exit code for SIGINT
INTERNALERROR>     ~~~~~~~~^^^^^
INTERNALERROR> SystemExit: 130
mainloop: caught unexpected SystemExit!

========================================== 30 failed, 763 passed in 33.37s ==========================================
make: *** [test] Error 3