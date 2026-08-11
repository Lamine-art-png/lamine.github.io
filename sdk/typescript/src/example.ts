import { AgroAIPlatformClient } from "./client.js";

const client = new AgroAIPlatformClient();
console.log(await client.me());
console.log(await client.usage());
