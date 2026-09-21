import type { QueryClient } from "@tanstack/react-query";

export function forgetSession(client: QueryClient) {
  // Keep the observed profile query attached while replacing authenticated data.
  void client.cancelQueries();
  client.removeQueries({
    predicate: (query) => query.queryKey[0] !== "profile",
  });
  client.setQueryData(["profile"], null);
}
