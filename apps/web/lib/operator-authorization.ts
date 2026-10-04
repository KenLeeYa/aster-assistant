const API = "http://127.0.0.1:8765/api/v1";

const intentHeaders = {
  "Content-Type": "application/json",
  "X-KY-JARVIS-Intent": "ui-v1",
};

export type OperatorStatus = {
  configured: boolean;
  registered: boolean;
  authenticator: "platform";
  user_verification: "required";
  grant_mode: "single-action";
};

export type OperatorAction = {
  method: "POST" | "DELETE";
  path: string;
  body: Record<string, unknown>;
};

type RegistrationOptionsJSON = Omit<
  PublicKeyCredentialCreationOptions,
  "challenge" | "excludeCredentials" | "user"
> & {
  challenge: string;
  excludeCredentials?: Array<Omit<PublicKeyCredentialDescriptor, "id"> & { id: string }>;
  user: Omit<PublicKeyCredentialUserEntity, "id"> & { id: string };
};

type AuthenticationOptionsJSON = Omit<
  PublicKeyCredentialRequestOptions,
  "allowCredentials" | "challenge"
> & {
  allowCredentials?: Array<Omit<PublicKeyCredentialDescriptor, "id"> & { id: string }>;
  challenge: string;
};

function decodeBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = window.atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function creationOptionsFromJSON(
  options: RegistrationOptionsJSON,
): PublicKeyCredentialCreationOptions {
  return {
    ...options,
    challenge: decodeBase64Url(options.challenge),
    user: { ...options.user, id: decodeBase64Url(options.user.id) },
    excludeCredentials: options.excludeCredentials?.map((credential) => ({
      ...credential,
      id: decodeBase64Url(credential.id),
    })),
  };
}

function requestOptionsFromJSON(
  options: AuthenticationOptionsJSON,
): PublicKeyCredentialRequestOptions {
  return {
    ...options,
    challenge: decodeBase64Url(options.challenge),
    allowCredentials: options.allowCredentials?.map((credential) => ({
      ...credential,
      id: decodeBase64Url(credential.id),
    })),
  };
}

function registrationCredentialToJSON(credential: PublicKeyCredential) {
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: encodeBase64Url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      attestationObject: encodeBase64Url(response.attestationObject),
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
      transports: response.getTransports?.() ?? ["internal"],
    },
  };
}

function authenticationCredentialToJSON(credential: PublicKeyCredential) {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: encodeBase64Url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      authenticatorData: encodeBase64Url(response.authenticatorData),
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
      signature: encodeBase64Url(response.signature),
      userHandle: response.userHandle ? encodeBase64Url(response.userHandle) : null,
    },
  };
}

async function responseError(response: Response, fallback: string): Promise<Error> {
  const payload = (await response.json().catch(() => ({}))) as { detail?: string };
  return new Error(payload.detail ?? fallback);
}

function requireWebAuthn() {
  if (window.location.origin !== "http://localhost:3000") {
    throw new Error("Windows Hello 只能從 http://localhost:3000 的 Command Center 使用");
  }
  if (!window.isSecureContext || !("PublicKeyCredential" in window)) {
    throw new Error("此瀏覽器環境不支援安全的 Windows Hello/WebAuthn");
  }
}

export async function loadOperatorStatus(): Promise<OperatorStatus> {
  const response = await fetch(`${API}/operator/status`, { cache: "no-store" });
  if (!response.ok) throw await responseError(response, "無法讀取桌面操作員狀態");
  return (await response.json()) as OperatorStatus;
}

export async function registerDesktopOperator(bootstrapSecret: string): Promise<OperatorStatus> {
  requireWebAuthn();
  const optionsResponse = await fetch(`${API}/operator/registration/options`, {
    method: "POST",
    headers: intentHeaders,
    body: JSON.stringify({ bootstrap_secret: bootstrapSecret }),
  });
  if (!optionsResponse.ok) {
    throw await responseError(optionsResponse, "無法開始 Windows Hello 註冊");
  }
  const request = (await optionsResponse.json()) as {
    challenge_id: string;
    options: RegistrationOptionsJSON;
  };
  const credential = (await navigator.credentials.create({
    publicKey: creationOptionsFromJSON(request.options),
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("Windows Hello 註冊已取消");
  const verifyResponse = await fetch(`${API}/operator/registration/verify`, {
    method: "POST",
    headers: intentHeaders,
    body: JSON.stringify({
      challenge_id: request.challenge_id,
      credential: registrationCredentialToJSON(credential),
    }),
  });
  if (!verifyResponse.ok) {
    throw await responseError(verifyResponse, "Windows Hello 註冊驗證失敗");
  }
  return (await verifyResponse.json()) as OperatorStatus;
}

export async function requestOperatorGrant(action: OperatorAction): Promise<string> {
  requireWebAuthn();
  const optionsResponse = await fetch(`${API}/operator/authentication/options`, {
    method: "POST",
    headers: intentHeaders,
    body: JSON.stringify(action),
  });
  if (!optionsResponse.ok) {
    throw await responseError(optionsResponse, "無法開始 Windows Hello 驗證");
  }
  const request = (await optionsResponse.json()) as {
    challenge_id: string;
    options: AuthenticationOptionsJSON;
  };
  const credential = (await navigator.credentials.get({
    publicKey: requestOptionsFromJSON(request.options),
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("Windows Hello 驗證已取消");
  const verifyResponse = await fetch(`${API}/operator/authentication/verify`, {
    method: "POST",
    headers: intentHeaders,
    body: JSON.stringify({
      challenge_id: request.challenge_id,
      credential: authenticationCredentialToJSON(credential),
    }),
  });
  if (!verifyResponse.ok) {
    throw await responseError(verifyResponse, "Windows Hello 驗證失敗");
  }
  const verified = (await verifyResponse.json()) as { grant_token: string };
  return verified.grant_token;
}
