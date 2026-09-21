import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { expect, it } from "vitest";
import { forgetSession } from "./session";

it("leaves the mounted profile observer ready for login after session expiry", () => {
  const client = new QueryClient();
  const observer = new QueryObserver(client, {
    queryKey: ["profile"],
    enabled: false,
  });
  const unsubscribe = observer.subscribe(() => {});
  client.setQueryData(["tenant", "private"], { secret: "test" });
  forgetSession(client);
  expect(observer.getCurrentResult().isPending).toBe(false);
  expect(observer.getCurrentResult().data).toBeNull();
  expect(client.getQueryData(["tenant", "private"])).toBeUndefined();
  client.setQueryData(["profile"], { person: "new-login" });
  expect(observer.getCurrentResult().data).toEqual({ person: "new-login" });
  unsubscribe();
  client.clear();
});
