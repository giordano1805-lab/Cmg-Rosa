$(function () {
    

});

getTipoGeneracion = function (tipo) {

    var tipoGeneracion = "";
    switch (tipo) {
        case "H":
            tipoGeneracion = "Hidroeléctrica";
            break;
        case "S":
            tipoGeneracion = "Solar";
            break;
        case "T":
            tipoGeneracion = "Termoeléctrica";
            break;
        case "E":
            tipoGeneracion = "Eólica";
            break;
        default:
            tipoGeneracion = tipo;
            break;
    }

    return tipoGeneracion;

}

getColorCombustible = function(name) {            

    var color = "#fff";
    switch (name) {
        case 'HÍDRICO':
            color = '#4572A7';//(AZUL)
            break;
        case 'GAS':
            color = '#F79646';//(ROJO)
            break;
        case 'DIESEL':
            color = '#880000'; //(VERDE OSCURO)
            break;
        case 'RESIDUAL':
            color = '#477519'; //(MARRON)
            break;
        case 'BAGAZO':
            color = '#C3C3C3'; //(NARANJA)
            break;
        case 'EÓLICA':
            color = '#69C9E0'; //(CELESTE)
            break;
        case 'BIOGÁS':
            color = '#2CDD17'; //(VERDE CLARO)
            break;
        case 'CARBÓN':
            color = '#515151'; //(GRIS OSCURO)
            break;
        case 'SOLAR':
            color = '#FFFF70'; //(AMARILLO)
            break;
        case 'Hídrico':
            color = '#6699FF';//(AZUL)
            break;
        case 'Gas':
            color = '#FF3300';//(ROJO)
            break;
        case 'Diesel':
            color = '#477519'; //(VERDE OSCURO)
            break;
        case 'Residual':
            color = '#AC5930'; //(MARRON)
            break;
        case 'Carbón':
            color = '#515151'; //(GRIS OSCURO)
            break;
        case 'Solar':
            color = '#FFFF70'; //(AMARILLO)
            break;
        case 'Eólica':
            color = '#69C9E0'; //(AMARILLO)
            break;
        case 'NAFTA & GAS REFINERÍA':
            color = '#27F587'; //(AMARILLO)
            break;
        case 'Otros':
            color = '#F5B67F';
            break;
    }

    return color;
}