import { AgroAIPlatformClient } from "./client";

const client = new AgroAIPlatformClient();
console.log(await client.me());
console.log(await client.providers());
