document.addEventListener('DOMContentLoaded', () => {

    // =================================================================
    // --- NAVIGATION LOGIC ---
    // =================================================================
    const navOpenBtn = document.getElementById('nav-open-btn');
    const navCloseBtn = document.getElementById('nav-close-btn');
    const navBackdrop = document.getElementById('nav-backdrop');
    const navList = document.getElementById('primary-navigation');
    const navLinks = document.querySelectorAll('#primary-navigation a');
    const header = document.querySelector('.header-blue');

    function openNav() {
        if (!navList) return;
        navList.setAttribute('data-visible', 'true');
        if (navBackdrop) navBackdrop.classList.add('visible');
        document.body.style.overflow = 'hidden'; // Lock background scroll
    }

    function closeNav() {
        if (!navList) return;
        navList.setAttribute('data-visible', 'false');
        if (navBackdrop) navBackdrop.classList.remove('visible');
        document.body.style.overflow = ''; // Restore scroll
    }

    // Toggle Mobile Menu
    if (navOpenBtn) {
        navOpenBtn.addEventListener('click', openNav);
    }

    if (navCloseBtn) {
        navCloseBtn.addEventListener('click', closeNav);
    }

    if (navBackdrop) {
        navBackdrop.addEventListener('click', closeNav);
    }

    // Close menu when clicking links (Mobile)
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            if (window.innerWidth <= 1024) {
                // Do not close if clicking a dropdown toggle (they toggle submenus)
                if(!link.classList.contains('dropdown-toggle')) {
                    closeNav();
                } else {
                    // If it is a dropdown toggle, check if it's the Academy nav which has a real link
                    // If clicking exactly the chevron, open dropdown. Else if it has an actual link, let it navigate
                    if (e.target.classList.contains('fa-chevron-down')) {
                        // Let the toggle logic handle it
                    } else if (link.getAttribute('href') !== '#') {
                        closeNav(); // Proceed with navigation
                    }
                }
            }
        });
    });

    // Handle Mobile Dropdowns (Click-based)
    const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
    dropdownToggles.forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            if (window.innerWidth <= 1024) {
                // Only prevent default if we clicked the chevron OR the toggle doesn't have a real link
                if (e.target.classList.contains('fa-chevron-down') || toggle.getAttribute('href') === '#') {
                    e.preventDefault();
                    const parent = toggle.closest('.has-dropdown');
                    if (parent) {
                        // Close other open dropdowns in the drawer
                        document.querySelectorAll('.has-dropdown.active').forEach(item => {
                            if (item !== parent) item.classList.remove('active');
                        });
                        parent.classList.toggle('active');
                    }
                }
            }
        });
    });

    // Reset mobile states on window resize
    window.addEventListener('resize', () => {
        if (window.innerWidth > 1024) {
            closeNav();
            document.querySelectorAll('.has-dropdown.active').forEach(item => {
                item.classList.remove('active');
            });
        }
    });

    // --- Header Scroll Effect ---
    window.addEventListener('scroll', () => {
        if (header) {
            if (window.scrollY > 50) {
                header.classList.add('scrolled');
            } else {
                header.classList.remove('scrolled');
            }
        }
    });

    // --- Active Link Highlighting ---
    function highlightActiveLink() {
        const currentPath = window.location.pathname;
        navLinks.forEach(link => {
            const linkPath = link.getAttribute('href');
            if (currentPath === linkPath) {
                link.classList.add('active');
            } else if (linkPath !== '/' && currentPath.startsWith(linkPath)) {
                // Secondary check for sub-routes
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    }

    highlightActiveLink();
});