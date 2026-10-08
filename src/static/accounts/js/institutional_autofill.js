// Compatibility entry point. All behavior lives in the shared component.
(() => {
    if (window.NovaDeskIdentity) { window.NovaDeskIdentity.initialize(); return; }
    const url = document.currentScript?.src.replace('/accounts/js/institutional_autofill.js', '/shared/js/institutional_identity.js');
    if (!url || document.querySelector('script[data-novadesk-identity-loader]')) return;
    const script = document.createElement('script');
    script.src = url;
    script.dataset.novadeskIdentityLoader = 'true';
    document.head.appendChild(script);
})();
