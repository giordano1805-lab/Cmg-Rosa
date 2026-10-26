var controlador = siteRoot + 'eventos/relevantes/'

$(function () {
    $('#FechaDesde').change({
    });

    $('#FechaHasta').change({
    });

    $('#cbFamilia').val("0");
    $('#cbEmpresa').val("0");
    
    buscarEvento();

    $('#btnBuscar').click(function () {
        buscarEvento();
    });

    $('#cbTipoEmpresa').change(function () {
        cargarEmpresas();
    });

    $(window).resize(function () {
        $('#listado').css("width", $('#mainLayout').width() + "px");
    });

    $('#btnExportar').click(function () {
        exportar();
    });
});

buscarEvento = function () {
    pintarPaginado();
    mostrarListado(1);
}

pintarPaginado = function () {
    $.ajax({
        type: 'POST',
        url: controlador + "paginado",
        /*data: $('#frmBusqueda').serialize(),*/
        data: {
            FechaInicio: GetDateNormalFormat($('#FechaDesde').val()),
            FechaFin: GetDateNormalFormat($('#FechaHasta').val()),
            IdTipoEvento: $('#hfIdTipoEvento').val(),
            Version: $('#hfVersion').val(),
            Turno: $('#hfTurno').val(),
            IdTipoEmpresa: $('#cbTipoEmpresa').val(),
            IdEmpresa: $('#cbEmpresa').val(),
            IdFamilia: $('#cbFamilia').val(),
            IndInterrupcion: $('#hfIndInterrupcion').val()
        },
        success: function (evt) {
            $('#paginado').html(evt);
            mostrarPaginado();
        },
        error: function () {
            mostrarError();
        }
    });
}

cargarEmpresas = function () {
    $.ajax({
        type: 'POST',
        url: controlador + 'cargarempresas',
        dataType: 'json',
        data: { idTipoEmpresa: $('#cbTipoEmpresa').val() },
        cache: false,
        success: function (aData) {
            $('#cbEmpresa').get(0).options.length = 0;
            $('#cbEmpresa').get(0).options[0] = new Option("--SELECCIONE--", "");
            $.each(aData, function (i, item) {
                $('#cbEmpresa').get(0).options[$('#cbEmpresa').get(0).options.length] = new Option(item.Text, item.Value);
            });
        },
        error: function () {
            mostrarError();
        }
    });
}

mostrarListado = function (nroPagina) {
    $('#hfNroPagina').val(nroPagina);
    $.ajax({
        type: 'POST',
        url: controlador + "lista",
        /*data: $('#frmBusqueda').serialize(),*/
        data: {
            FechaInicio: GetDateNormalFormat($('#FechaDesde').val()),
            FechaFin: GetDateNormalFormat($('#FechaHasta').val()),
            IdTipoEvento: $('#hfIdTipoEvento').val(),
            Version: $('#hfVersion').val(),
            Turno: $('#hfTurno').val(),
            IdTipoEmpresa: $('#cbTipoEmpresa').val(),
            IdEmpresa: $('#cbEmpresa').val(),
            IdFamilia: $('#cbFamilia').val(),
            IndInterrupcion: $('#hfIndInterrupcion').val(),
            NroPagina: nroPagina
        },
        success: function (evt) {
            $('#listado').css("width", $('#mainLayout').width() + "px");
            $('#listado').html(evt);
            $('#tabla').dataTable({
                "scrollY": 490,                
                "sDom": 't',
                "ordering": false,
                "iDisplayLength": 50
            });
        },
        error: function () {
            mostrarError();
        }
    });
}

exportar = function () {
    var model = {
        FechaInicio: GetDateNormalFormat($('#FechaDesde').val()),
        FechaFin: GetDateNormalFormat($('#FechaHasta').val()),
        IdTipoEvento: $('#hfIdTipoEvento').val(),
        Version: $('#hfVersion').val(),
        Turno: $('#hfTurno').val(),
        IdTipoEmpresa: $('#cbTipoEmpresa').val(),
        IdEmpresa: $('#cbEmpresa').val(),
        IdFamilia: $('#cbFamilia').val(),
        IndInterrupcion: $('#hfIndInterrupcion').val()
    };

    let enlace = controlador + "ExportarEvento?"
        + $.param(model);

    window.open(enlace, '_blank');
}

pintarBusqueda = function (nroPagina) {
    mostrarListado(nroPagina);
}

verEvento = function (id) {
    $.ajax({
        type: 'POST',
        data: { idEvento:id },
        url: controlador + 'detalle',
        success: function (evt) {
            $('#contenidoEdicion').html(evt);
            setTimeout(function () {
                $('#popupEdicion').bPopup({
                    autoClose: false
                });

            }, 50);
            
            $('#btnCancelar').click(function () {
                $('#popupEdicion').bPopup().close();
            });
        },
        error: function () {
            mostrarError();
        }
    });
}

mostrarError = function () {
    alert('Ha ocurrido un error.');
}

// Convierte formato yyyy-mm-dd a dd/mm/yyyy
GetDateNormalFormat = function (fechaFormatoISO) {
    let fechaNormal = fechaFormatoISO.substring(8, 10) + "/" + fechaFormatoISO.substring(5, 7) + "/" + fechaFormatoISO.substring(0, 4);
    return fechaNormal;
}