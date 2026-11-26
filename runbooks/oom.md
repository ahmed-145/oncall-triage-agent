### Memory recovery

Confirm the pod's previous termination reason is OOMKilled. Compare working set
and the container limit before deciding whether to revert the release or change
the limit. After recovery, confirm the restart count has stabilized and order
requests succeed.
