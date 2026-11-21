import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";

const { createGQLClient } = await import(pathToFileURL(process.argv[2]));
const server = createServer(async (request, response) => {
  let body = "";
  for await (const chunk of request) body += chunk;
  try {
    assert.equal(request.url, "/query");
    assert.equal(request.headers.authorization, "Basic " + Buffer.from("fixture-token:").toString("base64"));
    assert.equal(JSON.parse(body).query, "query { __typename }");
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ data: { __typename: "Query" } }));
  } catch (error) {
    response.writeHead(400, { "content-type": "application/json" });
    response.end(JSON.stringify({ errors: [{ message: error.message }] }));
  }
});
server.listen(0, "127.0.0.1");
await once(server, "listening");
try {
  const client = createGQLClient(server.address().port, "fixture-token");
  assert.deepEqual(await client.request("query { __typename }"), { __typename: "Query" });
  console.log(`Built SDK GraphQL client completed authenticated HTTP query on ${process.version}`);
} finally {
  server.close();
}
