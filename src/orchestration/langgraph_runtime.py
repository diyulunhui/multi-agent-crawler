from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

try:
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except ModuleNotFoundError:
    # 在未安装 langgraph 的环境下保留最小可运行能力，避免影响现有单测与本地开发。
    LANGGRAPH_AVAILABLE = False
    END = "__end__"

    NodeFn = Callable[[dict[str, object]], dict[str, object]]
    RouteFn = Callable[[dict[str, object]], str]

    @dataclass(frozen=True)
    class _ConditionalEdge:
        route_fn: RouteFn
        path_map: dict[str, str]

    class _CompiledStateGraph:
        def __init__(
            self,
            entry_point: str,
            nodes: dict[str, NodeFn],
            edges: dict[str, list[str]],
            conditional_edges: dict[str, _ConditionalEdge],
        ) -> None:
            self._entry_point = entry_point
            self._nodes = nodes
            self._edges = edges
            self._conditional_edges = conditional_edges

        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            current = self._entry_point
            max_steps = 128
            step = 0
            next_state = dict(state)

            while current != END:
                step += 1
                if step > max_steps:
                    raise RuntimeError("StateGraph 执行超过最大步数，疑似存在循环。")

                node = self._nodes.get(current)
                if node is None:
                    raise ValueError(f"未找到节点: {current}")
                updates = node(next_state)
                if updates:
                    next_state.update(updates)

                conditional = self._conditional_edges.get(current)
                if conditional is not None:
                    route = conditional.route_fn(next_state)
                    target = conditional.path_map.get(route)
                    if target is None:
                        raise ValueError(f"节点 {current} 条件分支未映射: {route}")
                    current = target
                    continue

                direct_edges = self._edges.get(current, [])
                current = direct_edges[0] if direct_edges else END

            return next_state

    class StateGraph:  # type: ignore[no-redef]
        def __init__(self, _state_schema: type[object] | None = None) -> None:
            self._nodes: dict[str, NodeFn] = {}
            self._edges: dict[str, list[str]] = defaultdict(list)
            self._conditional_edges: dict[str, _ConditionalEdge] = {}
            self._entry_point: str | None = None

        def add_node(self, node_name: str, node_fn: NodeFn) -> None:
            self._nodes[node_name] = node_fn

        def add_edge(self, source: str, target: str) -> None:
            self._edges[source].append(target)

        def add_conditional_edges(
            self,
            source: str,
            route_fn: RouteFn,
            path_map: dict[str, str],
        ) -> None:
            self._conditional_edges[source] = _ConditionalEdge(route_fn=route_fn, path_map=dict(path_map))

        def set_entry_point(self, node_name: str) -> None:
            self._entry_point = node_name

        def compile(self) -> _CompiledStateGraph:
            if not self._entry_point:
                raise ValueError("StateGraph 缺少 entry_point。")
            return _CompiledStateGraph(
                entry_point=self._entry_point,
                nodes=dict(self._nodes),
                edges={name: list(targets) for name, targets in self._edges.items()},
                conditional_edges=dict(self._conditional_edges),
            )
