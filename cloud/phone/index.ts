// JARVIS phone app: the relay's entry point in the owner's own Supabase project. JARVIS deploys it (/phone in JARVIS)
// with the gateway's JWT check off: phones and the laptop cannot send a Supabase JWT, and every request is checked here
// instead (each phone's own Ed25519 signature, the laptop's own secret).
import { makeRelay } from './relay.js';

declare const EdgeRuntime: { waitUntil(promise: Promise<unknown>): void };

const relay = makeRelay(Deno.env.toObject(), { waitUntil: promise => EdgeRuntime.waitUntil(promise) });

Deno.serve(request => relay.handle(request));
